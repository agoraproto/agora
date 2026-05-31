"""Tests for Sprint 31 RFQ + Sprint 34a (buyer signatures) + Sprint 34b
(bid expiration, bid_hash uniqueness)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey

# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _b58encode(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = alphabet[rem] + out
    pad = 0
    for b in raw:
        if b == 0:
            pad += 1
        else:
            break
    return "1" * pad + (out or "1")


def _did_doc(did: str, signing_key: SigningKey) -> dict[str, Any]:
    raw = b"\xed\x01" + bytes(signing_key.verify_key)
    return {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": "z" + _b58encode(raw),
            }
        ],
    }


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _constraints_hash(constraints: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(constraints)).hexdigest()


def _sign(signing_key: SigningKey, payload: dict[str, Any]) -> str:
    return base64.b64encode(signing_key.sign(_canonical_bytes(payload)).signature).decode()


def _create_request_signed(
    buyer_did: str,
    signing_key: SigningKey,
    *,
    title: str,
    description: str = "",
    capability: str | None = None,
    constraints: dict[str, Any] | None = None,
    max_price_micro_usdc: int = 10_000,
    currency: str = "USDC",
    deadline: str | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a full signed create_request body."""
    constraints = constraints or {}
    if nonce is None:
        nonce = secrets.token_hex(8)
    signed_payload = {
        "intent": "create_request",
        "buyer_did": buyer_did,
        "title": title,
        "description": description,
        "capability": capability,
        "constraints_hash": _constraints_hash(constraints),
        "max_price_micro_usdc": max_price_micro_usdc,
        "currency": currency,
        "deadline": deadline,
        "nonce": nonce,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    signature = _sign(signing_key, signed_payload)
    return {
        "buyer_did": buyer_did,
        "title": title,
        "description": description,
        "capability": capability,
        "constraints": constraints,
        "max_price_micro_usdc": max_price_micro_usdc,
        "currency": currency,
        "deadline": deadline,
        "signed_payload": signed_payload,
        "signature": signature,
        "nonce": nonce,
    }


def _accept_bid_signed(
    buyer_did: str,
    signing_key: SigningKey,
    *,
    request_id: str,
    bid_id: str,
    bid_hash: str,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a full signed accept_bid body."""
    if nonce is None:
        nonce = secrets.token_hex(8)
    signed_payload = {
        "intent": "accept_bid",
        "buyer_did": buyer_did,
        "request_id": request_id,
        "bid_id": bid_id,
        "bid_hash": bid_hash,
        "nonce": nonce,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    signature = _sign(signing_key, signed_payload)
    return {
        "buyer_did": buyer_did,
        "bid_hash": bid_hash,
        "signed_payload": signed_payload,
        "signature": signature,
        "nonce": nonce,
    }


def _bid_signed(
    provider_did: str,
    signing_key: SigningKey,
    *,
    request_id: str,
    price_micro_usdc: int = 9_000,
    currency: str = "USDC",
    message: str = "",
    expires_in_minutes: float = 5,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a full signed bid body."""
    nonce = nonce or secrets.token_hex(8)
    expires_at = (datetime.now(UTC) + timedelta(minutes=expires_in_minutes)).isoformat()
    signed_payload = {
        "request_id": request_id,
        "provider_did": provider_did,
        "price_micro_usdc": price_micro_usdc,
        "currency": currency,
        "nonce": nonce,
        "expires_at": expires_at,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    signature = _sign(signing_key, signed_payload)
    return {
        "provider_did": provider_did,
        "price_micro_usdc": price_micro_usdc,
        "currency": currency,
        "message": message,
        "signed_payload": signed_payload,
        "signature": signature,
        "nonce": nonce,
        "expires_at": expires_at,
    }


async def _register_agent(client: AsyncClient, did: str, key: SigningKey) -> None:
    payload = {
        "did_document": _did_doc(did, key),
        "name": did.rsplit(":", 1)[-1],
        "description": "RFQ test agent",
        "owner_did": did,
        "capabilities": [{"type": "CodeReview"}],
        "pricing": {"model": "per_request", "currency": "USDC", "base_price": "0.01"},
        "endpoint_url": "",
        "stake_eur": "5.00",
    }
    r = await client.post("/v1/agents/register", json=payload)
    assert r.status_code == 201, r.text


# ─────────────────────────────────────────────────────────────────────
# Sprint 31 happy paths — now with Sprint 34a buyer signatures
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_rfq_request(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    did = "did:agora:buyer_rfq"
    await _register_agent(client, did, buyer_key)

    body = _create_request_signed(
        did, buyer_key,
        title="Need a code review",
        description="Review one small patch.",
        capability="CodeReview",
        constraints={"language": "python"},
    )
    r = await client.post("/v1/requests", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "open"
    assert out["max_price_micro_usdc"] == 10_000

    listed = await client.get("/v1/requests", params={"capability": "CodeReview"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_rfq_rejects_price_above_house_rule(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    did = "did:agora:buyer_price"
    await _register_agent(client, did, buyer_key)

    body = _create_request_signed(did, buyer_key, title="Too expensive", max_price_micro_usdc=10_001)
    r = await client.post("/v1/requests", json=body)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_submit_signed_bid_and_accept(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_bid"
    provider_did = "did:agora:provider_bid"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (
        await client.post(
            "/v1/requests",
            json=_create_request_signed(
                buyer_did, buyer_key,
                title="Signed bid please", capability="CodeReview",
            ),
        )
    ).json()
    request_id = created["id"]
    bid_body = await client.post(
        f"/v1/requests/{request_id}/bids",
        json=_bid_signed(provider_did, provider_key, request_id=request_id),
    )
    assert bid_body.status_code == 201, bid_body.text
    bid = bid_body.json()
    assert bid["status"] == "pending"
    assert len(bid["bid_hash"]) == 64

    accept_body = _accept_bid_signed(
        buyer_did, buyer_key,
        request_id=request_id, bid_id=bid["id"], bid_hash=bid["bid_hash"],
    )
    accepted = await client.post(
        f"/v1/requests/{request_id}/bids/{bid['id']}/accept",
        json=accept_body,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["request"]["status"] == "accepted"
    assert accepted.json()["bid"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_bid_rejects_replayed_nonce(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_replay"
    provider_did = "did:agora:provider_replay"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (
        await client.post(
            "/v1/requests",
            json=_create_request_signed(buyer_did, buyer_key, title="Replay check"),
        )
    ).json()
    bid_body = _bid_signed(
        provider_did, provider_key,
        request_id=created["id"], price_micro_usdc=1_000, nonce="nonce-replay",
    )

    first = await client.post(f"/v1/requests/{created['id']}/bids", json=bid_body)
    assert first.status_code == 201, first.text
    second = await client.post(f"/v1/requests/{created['id']}/bids", json=bid_body)
    assert second.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# Sprint 34a — buyer signature regression tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_request_requires_signed_payload(client: AsyncClient) -> None:
    """Pydantic-level rejection when signed_payload field is missing entirely."""
    buyer_key = SigningKey.generate()
    did = "did:agora:buyer_nosig"
    await _register_agent(client, did, buyer_key)

    r = await client.post("/v1/requests", json={
        "buyer_did": did,
        "title": "Unsigned",
        "max_price_micro_usdc": 10_000,
        # missing: signed_payload, signature, nonce
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_request_rejects_wrong_signature(client: AsyncClient) -> None:
    """Attacker A signs a request claiming to be victim B."""
    victim_key = SigningKey.generate()
    attacker_key = SigningKey.generate()
    victim_did = "did:agora:buyer_victim"
    attacker_did = "did:agora:buyer_attacker"
    await _register_agent(client, victim_did, victim_key)
    await _register_agent(client, attacker_did, attacker_key)

    # Build a request body claiming to be the victim, but signed by attacker
    body = _create_request_signed(victim_did, attacker_key, title="Identity theft attempt")
    r = await client.post("/v1/requests", json=body)
    assert r.status_code == 400
    assert "signature" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_create_request_rejects_wrong_intent(client: AsyncClient) -> None:
    """Sprint 34a intent discriminator: signed payload with intent='accept_bid'
    must not be accepted by the create_request endpoint."""
    buyer_key = SigningKey.generate()
    did = "did:agora:buyer_wrongintent"
    await _register_agent(client, did, buyer_key)

    body = _create_request_signed(did, buyer_key, title="Wrong intent")
    body["signed_payload"]["intent"] = "accept_bid"
    body["signature"] = _sign(buyer_key, body["signed_payload"])

    r = await client.post("/v1/requests", json=body)
    assert r.status_code == 400
    assert "intent" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_create_request_rejects_payload_title_mismatch(client: AsyncClient) -> None:
    """Tampering with the visible title while keeping signed_payload.title intact."""
    buyer_key = SigningKey.generate()
    did = "did:agora:buyer_tamper"
    await _register_agent(client, did, buyer_key)

    body = _create_request_signed(did, buyer_key, title="Honest title")
    body["title"] = "Tampered title"  # diverges from signed_payload.title

    r = await client.post("/v1/requests", json=body)
    assert r.status_code == 400
    assert "title" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_accept_bid_requires_signed_payload(client: AsyncClient) -> None:
    """Old (pre-Sprint-34a) accept_bid body shape must be rejected."""
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_acc_nosig"
    provider_did = "did:agora:provider_acc_nosig"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (
        await client.post(
            "/v1/requests",
            json=_create_request_signed(buyer_did, buyer_key, title="Need acc"),
        )
    ).json()
    bid = (
        await client.post(
            f"/v1/requests/{created['id']}/bids",
            json=_bid_signed(provider_did, provider_key, request_id=created["id"]),
        )
    ).json()

    r = await client.post(
        f"/v1/requests/{created['id']}/bids/{bid['id']}/accept",
        json={"buyer_did": buyer_did, "bid_hash": bid["bid_hash"]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_accept_bid_rejects_wrong_intent(client: AsyncClient) -> None:
    """Cross-protocol replay attempt: signature for create_request fed into accept."""
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_acc_wi"
    provider_did = "did:agora:provider_acc_wi"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (await client.post("/v1/requests", json=_create_request_signed(
        buyer_did, buyer_key, title="acc wi"))).json()
    bid = (await client.post(
        f"/v1/requests/{created['id']}/bids",
        json=_bid_signed(provider_did, provider_key, request_id=created["id"]),
    )).json()

    accept_body = _accept_bid_signed(
        buyer_did, buyer_key,
        request_id=created["id"], bid_id=bid["id"], bid_hash=bid["bid_hash"],
    )
    accept_body["signed_payload"]["intent"] = "create_request"
    accept_body["signature"] = _sign(buyer_key, accept_body["signed_payload"])

    r = await client.post(
        f"/v1/requests/{created['id']}/bids/{bid['id']}/accept", json=accept_body,
    )
    assert r.status_code == 400
    assert "intent" in r.json().get("detail", "")


# ─────────────────────────────────────────────────────────────────────
# Sprint 34b — bid expiration regression tests
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_bid_rejects_already_expired(client: AsyncClient) -> None:
    """A bid whose expires_at is already in the past at submit time is rejected."""
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_be"
    provider_did = "did:agora:provider_be"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (await client.post("/v1/requests", json=_create_request_signed(
        buyer_did, buyer_key, title="bid expired"))).json()

    bid_body = _bid_signed(
        provider_did, provider_key,
        request_id=created["id"], expires_in_minutes=-2,  # 2 minutes ago
    )
    r = await client.post(f"/v1/requests/{created['id']}/bids", json=bid_body)
    assert r.status_code == 400
    assert "expir" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_accept_bid_rejects_expired_bid(client: AsyncClient) -> None:
    """Bid was valid at submit, but expired before accept. 410 Gone."""
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_acc_exp"
    provider_did = "did:agora:provider_acc_exp"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    created = (await client.post("/v1/requests", json=_create_request_signed(
        buyer_did, buyer_key, title="acc exp"))).json()

    # Submit with expires_at 1 second in the future
    bid_body = _bid_signed(
        provider_did, provider_key,
        request_id=created["id"], expires_in_minutes=1/60,  # 1 second
    )
    bid = (await client.post(f"/v1/requests/{created['id']}/bids", json=bid_body)).json()
    assert "id" in bid

    # Wait for expiry
    await asyncio.sleep(2)

    accept_body = _accept_bid_signed(
        buyer_did, buyer_key,
        request_id=created["id"], bid_id=bid["id"], bid_hash=bid["bid_hash"],
    )
    r = await client.post(
        f"/v1/requests/{created['id']}/bids/{bid['id']}/accept", json=accept_body,
    )
    assert r.status_code == 410
    assert "expir" in r.json().get("detail", "").lower()


# ─────────────────────────────────────────────────────────────────────
# Sprint 36d — buyer-side replay protection via signed_actions table
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_request_rejects_replayed_nonce(client: AsyncClient) -> None:
    """POSTing the same signed create_request body twice must yield 201, 409."""
    buyer_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_replay_create"
    await _register_agent(client, buyer_did, buyer_key)

    body = _create_request_signed(
        buyer_did, buyer_key, title="Replay-protected create",
    )

    first = await client.post("/v1/requests", json=body)
    assert first.status_code == 201, first.text
    second = await client.post("/v1/requests", json=body)
    assert second.status_code == 409
    detail = second.json().get("detail", "")
    assert "nonce" in detail.lower()
    assert "rfq.create" in detail


@pytest.mark.asyncio
async def test_accept_bid_rejects_replayed_nonce_across_requests(
    client: AsyncClient,
) -> None:
    """A buyer's accept-nonce must be one-shot across DIFFERENT requests, too.

    Otherwise an attacker who captured one accept can replay it against any
    later bid the same buyer makes.
    """
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    buyer_did = "did:agora:buyer_replay_accept"
    provider_did = "did:agora:provider_replay_accept"
    await _register_agent(client, buyer_did, buyer_key)
    await _register_agent(client, provider_did, provider_key)

    # First request → bid → accept (legitimately) with nonce X.
    r = await client.post(
        "/v1/requests",
        json=_create_request_signed(buyer_did, buyer_key, title="A"),
    )
    assert r.status_code == 201, r.text
    req_a = r.json()
    r = await client.post(
        f"/v1/requests/{req_a['id']}/bids",
        json=_bid_signed(provider_did, provider_key, request_id=req_a["id"]),
    )
    assert r.status_code == 201, r.text
    bid_a = r.json()
    shared_nonce = "shared-accept-nonce"
    accept_a = _accept_bid_signed(
        buyer_did, buyer_key,
        request_id=req_a["id"], bid_id=bid_a["id"], bid_hash=bid_a["bid_hash"],
        nonce=shared_nonce,
    )
    r = await client.post(
        f"/v1/requests/{req_a['id']}/bids/{bid_a['id']}/accept",
        json=accept_a,
    )
    assert r.status_code == 200, r.text

    # Second request → bid → try accept with SAME nonce X by same buyer.
    r = await client.post(
        "/v1/requests",
        json=_create_request_signed(buyer_did, buyer_key, title="B"),
    )
    assert r.status_code == 201, r.text
    req_b = r.json()
    r = await client.post(
        f"/v1/requests/{req_b['id']}/bids",
        json=_bid_signed(provider_did, provider_key, request_id=req_b["id"]),
    )
    assert r.status_code == 201, r.text
    bid_b = r.json()
    accept_b = _accept_bid_signed(
        buyer_did, buyer_key,
        request_id=req_b["id"], bid_id=bid_b["id"], bid_hash=bid_b["bid_hash"],
        nonce=shared_nonce,  # ← REPLAY across requests
    )
    r = await client.post(
        f"/v1/requests/{req_b['id']}/bids/{bid_b['id']}/accept",
        json=accept_b,
    )
    assert r.status_code == 409
    assert "rfq.accept" in r.json().get("detail", "")
