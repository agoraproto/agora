"""Tests for the agent registry against an in-memory DB."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


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
