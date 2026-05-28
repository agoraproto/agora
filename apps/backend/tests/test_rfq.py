"""Tests for Sprint 31 RFQ request and bid endpoints."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey


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


@pytest.mark.asyncio
async def test_create_and_list_rfq_request(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    await _register_agent(client, "did:agora:buyer_rfq", buyer_key)

    r = await client.post(
        "/v1/requests",
        json={
            "buyer_did": "did:agora:buyer_rfq",
            "title": "Need a code review",
            "description": "Review one small patch.",
            "capability": "CodeReview",
            "constraints": {"language": "python"},
            "max_price_micro_usdc": 10_000,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["max_price_micro_usdc"] == 10_000

    listed = await client.get("/v1/requests", params={"capability": "CodeReview"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_rfq_rejects_price_above_house_rule(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    await _register_agent(client, "did:agora:buyer_price", buyer_key)

    r = await client.post(
        "/v1/requests",
        json={
            "buyer_did": "did:agora:buyer_price",
            "title": "Too expensive",
            "max_price_micro_usdc": 10_001,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_submit_signed_bid_and_accept(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    await _register_agent(client, "did:agora:buyer_bid", buyer_key)
    await _register_agent(client, "did:agora:provider_bid", provider_key)

    created = (
        await client.post(
            "/v1/requests",
            json={
                "buyer_did": "did:agora:buyer_bid",
                "title": "Signed bid please",
                "capability": "CodeReview",
                "max_price_micro_usdc": 10_000,
            },
        )
    ).json()
    request_id = created["id"]
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    payload = {
        "request_id": request_id,
        "provider_did": "did:agora:provider_bid",
        "price_micro_usdc": 9_000,
        "currency": "USDC",
        "nonce": "nonce-123456",
        "expires_at": expires_at,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    signature = base64.b64encode(provider_key.sign(_canonical_bytes(payload)).signature).decode()

    bid = await client.post(
        f"/v1/requests/{request_id}/bids",
        json={
            "provider_did": "did:agora:provider_bid",
            "price_micro_usdc": 9_000,
            "currency": "USDC",
            "message": "Can do it.",
            "signed_payload": payload,
            "signature": signature,
            "nonce": "nonce-123456",
            "expires_at": expires_at,
        },
    )
    assert bid.status_code == 201, bid.text
    bid_body = bid.json()
    assert bid_body["status"] == "pending"
    assert len(bid_body["bid_hash"]) == 64

    accepted = await client.post(
        f"/v1/requests/{request_id}/bids/{bid_body['id']}/accept",
        json={"buyer_did": "did:agora:buyer_bid", "bid_hash": bid_body["bid_hash"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["request"]["status"] == "accepted"
    assert accepted.json()["bid"]["status"] == "accepted"


@pytest.mark.asyncio
async def test_bid_rejects_replayed_nonce(client: AsyncClient) -> None:
    buyer_key = SigningKey.generate()
    provider_key = SigningKey.generate()
    await _register_agent(client, "did:agora:buyer_replay", buyer_key)
    await _register_agent(client, "did:agora:provider_replay", provider_key)

    created = (
        await client.post(
            "/v1/requests",
            json={
                "buyer_did": "did:agora:buyer_replay",
                "title": "Replay check",
                "max_price_micro_usdc": 10_000,
            },
        )
    ).json()
    expires_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    payload = {
        "request_id": created["id"],
        "provider_did": "did:agora:provider_replay",
        "price_micro_usdc": 1_000,
        "currency": "USDC",
        "nonce": "nonce-replay",
        "expires_at": expires_at,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    signature = base64.b64encode(provider_key.sign(_canonical_bytes(payload)).signature).decode()
    body = {
        "provider_did": "did:agora:provider_replay",
        "price_micro_usdc": 1_000,
        "currency": "USDC",
        "message": "",
        "signed_payload": payload,
        "signature": signature,
        "nonce": "nonce-replay",
        "expires_at": expires_at,
    }

    first = await client.post(f"/v1/requests/{created['id']}/bids", json=body)
    assert first.status_code == 201, first.text
    second = await client.post(f"/v1/requests/{created['id']}/bids", json=body)
    assert second.status_code == 409
