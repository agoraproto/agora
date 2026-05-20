"""Tests for the agent registry against an in-memory DB."""

from __future__ import annotations

import base64
import json
import time

import pytest
from httpx import AsyncClient
from nacl.signing import SigningKey


def _make_register_payload(
    did: str = "did:agora:test_agent_0001",
    stake: str = "5.00",
    sponsor: dict | None = None,
    name: str = "test-agent",
) -> dict:
    payload: dict = {
        "did_document": {"id": did, "verificationMethod": []},
        "name": name,
        "description": "Test agent.",
        "owner_did": did,
        "capabilities": [{"type": "Echo"}],
        "pricing": {"model": "per_request", "currency": "EURC", "base_price": "0.50"},
        "endpoint_url": "https://example.com/echo",
        "stake_eur": stake,
    }
    if sponsor is not None:
        payload["sponsor"] = sponsor
    return payload


@pytest.mark.asyncio
async def test_register_self_owned_agent(client: AsyncClient) -> None:
    resp = await client.post("/v1/agents/register", json=_make_register_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["did"] == "did:agora:test_agent_0001"
    assert body["trust_level"] == "probation"
    assert len(body["webhook_secret"]) > 10
    assert any("Probation" in n for n in body["notes"])


@pytest.mark.asyncio
async def test_higher_stake_yields_verified_trust(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/agents/register",
        json=_make_register_payload(did="did:agora:trusted_one", stake="100.00"),
    )
    assert resp.status_code == 201
    assert resp.json()["trust_level"] == "verified"


@pytest.mark.asyncio
async def test_low_stake_without_sponsor_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/agents/register",
        json=_make_register_payload(did="did:agora:spammer", stake="1.00"),
    )
    assert resp.status_code == 400
    assert "minimum stake" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_did_prefix_rejected(client: AsyncClient) -> None:
    payload = _make_register_payload(did="did:web:example.com")
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 400
    assert "did:agora:" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_did_rejected(client: AsyncClient) -> None:
    payload = _make_register_payload(did="did:agora:dup_agent")
    first = await client.post("/v1/agents/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/v1/agents/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_get_agent_returns_profile_without_webhook(client: AsyncClient) -> None:
    payload = _make_register_payload(did="did:agora:fetchable")
    await client.post("/v1/agents/register", json=payload)
    resp = await client.get("/v1/agents/did:agora:fetchable")
    assert resp.status_code == 200
    body = resp.json()
    assert body["did"] == "did:agora:fetchable"
    assert "webhook_secret" not in body
    assert "webhook_secret_hash" not in body


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient) -> None:
    for i in range(3):
        await client.post(
            "/v1/agents/register",
            json=_make_register_payload(did=f"did:agora:multi_{i}", name=f"agent-{i}"),
        )
    resp = await client.get("/v1/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert {a["name"] for a in body["agents"]} == {"agent-0", "agent-1", "agent-2"}


@pytest.mark.asyncio
async def test_deactivate_agent(client: AsyncClient) -> None:
    payload = _make_register_payload(did="did:agora:to_kill")
    await client.post("/v1/agents/register", json=payload)
    resp = await client.delete("/v1/agents/did:agora:to_kill")
    assert resp.status_code == 200
    assert resp.json() == {"did": "did:agora:to_kill", "status": "archived"}
    fetched = await client.get("/v1/agents/did:agora:to_kill")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "archived"


# ═════════════════════════════════════════════════════════════════════
# Sponsor onboarding (ADR 007) — Sprint 9g
# ═════════════════════════════════════════════════════════════════════


def _b58encode(data: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(data, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    for b in data:
        if b == 0:
            out = "1" + out
        else:
            break
    return out or "1"


def _sponsor_did_document(verify_key_bytes: bytes, did: str) -> dict:
    """Build a DID doc with a real Ed25519 verificationMethod the
    server can recover."""
    multibase = "z" + _b58encode(b"\xed\x01" + verify_key_bytes)
    return {
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyMultibase": multibase,
            }
        ],
    }


async def _seed_eligible_sponsor(client: AsyncClient, session) -> tuple[str, SigningKey]:
    """Create a sponsor agent in the DB at trust=verified with 50 jobs."""
    from sqlalchemy import update

    from agora_api.db.models import Agent, TrustLevel

    sk = SigningKey.generate()
    vk_bytes = bytes(sk.verify_key)
    sponsor_did = "did:agora:sponsor_eligible"
    # First register normally (high stake -> verified) so the agents_repo
    # path runs and we get a proper Agent row.
    payload = _make_register_payload(did=sponsor_did, stake="100.00", name="sponsor-x")
    payload["did_document"] = _sponsor_did_document(vk_bytes, sponsor_did)
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 201, resp.text
    # Now bump jobs_completed past the ADR 007 threshold so the sponsor
    # passes the eligibility gate.
    await session.execute(
        update(Agent).where(Agent.did == sponsor_did).values(jobs_completed=60)
    )
    await session.commit()
    return sponsor_did, sk


def _sign_pledge(
    sk: SigningKey, *, new_agent_did: str, sponsor_did: str,
    stake_pledged: str = "5.00", valid_until_unix: int | None = None,
) -> dict:
    if valid_until_unix is None:
        valid_until_unix = int(time.time()) + 90 * 24 * 3600
    payload = json.dumps(
        {
            "agora_sponsor_version": 1,
            "new_agent_did": new_agent_did,
            "sponsor_did": sponsor_did,
            "stake_pledged": stake_pledged,
            "valid_until_unix": valid_until_unix,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    sig = sk.sign(payload).signature
    return {
        "sponsor_did": sponsor_did,
        "signature": base64.b64encode(sig).decode(),
        "stake_pledged": stake_pledged,
        "valid_until_unix": valid_until_unix,
    }


@pytest.mark.asyncio
async def test_sponsor_signature_accepted_when_valid(client: AsyncClient, session) -> None:
    sponsor_did, sk = await _seed_eligible_sponsor(client, session)
    new_did = "did:agora:sponsored_one"
    pledge = _sign_pledge(sk, new_agent_did=new_did, sponsor_did=sponsor_did)
    payload = _make_register_payload(did=new_did, stake="1.00", sponsor=pledge)
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 201, resp.text
    # ADR 007 / trust_level_from: has_sponsor -> TrustLevel.new
    assert resp.json()["trust_level"] == "new"


@pytest.mark.asyncio
async def test_sponsor_rejected_when_signature_is_garbage(
    client: AsyncClient, session
) -> None:
    sponsor_did, _ = await _seed_eligible_sponsor(client, session)
    pledge = {
        "sponsor_did": sponsor_did,
        "signature": base64.b64encode(b"\x00" * 64).decode(),  # all-zeros sig
        "stake_pledged": "5.00",
        "valid_until_unix": int(time.time()) + 86400,
    }
    payload = _make_register_payload(
        did="did:agora:sybil_attempt", stake="1.00", sponsor=pledge
    )
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 400
    assert "sponsorship rejected" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_sponsor_rejected_when_sponsor_not_eligible(
    client: AsyncClient, session
) -> None:
    """Fresh agent with no completed jobs can't sponsor others."""
    # Register a low-stake agent (trust=probation, jobs_completed=0)
    sk = SigningKey.generate()
    vk_bytes = bytes(sk.verify_key)
    weak_sponsor_did = "did:agora:weak_sponsor"
    payload = _make_register_payload(did=weak_sponsor_did, stake="5.00")
    payload["did_document"] = _sponsor_did_document(vk_bytes, weak_sponsor_did)
    await client.post("/v1/agents/register", json=payload)
    # They try to sponsor someone with a syntactically valid signature
    new_did = "did:agora:wants_in"
    pledge = _sign_pledge(sk, new_agent_did=new_did, sponsor_did=weak_sponsor_did)
    payload = _make_register_payload(did=new_did, stake="1.00", sponsor=pledge)
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "sponsorship rejected" in detail
    # eligibility error mentions trust level or jobs completed
    assert "trust_level" in detail or "completed jobs" in detail


@pytest.mark.asyncio
async def test_sponsor_rejected_when_sponsor_unknown(client: AsyncClient) -> None:
    """Pledge from a sponsor that has never been registered."""
    sk = SigningKey.generate()
    new_did = "did:agora:no_sponsor_for_you"
    pledge = _sign_pledge(
        sk, new_agent_did=new_did, sponsor_did="did:agora:does_not_exist"
    )
    payload = _make_register_payload(did=new_did, stake="1.00", sponsor=pledge)
    resp = await client.post("/v1/agents/register", json=payload)
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]
