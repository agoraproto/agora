"""Tests for /v1/search and /v1/match against an in-memory DB."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _payload(
    did: str,
    *,
    name: str = "agent",
    description: str = "",
    capability: str = "Echo",
    base_price: str = "0.50",
    stake: str = "25.00",
) -> dict:
    return {
        "did_document": {"id": did, "verificationMethod": []},
        "name": name,
        "description": description,
        "owner_did": did,
        "capabilities": [{"type": capability}],
        "pricing": {"model": "per_request", "currency": "EURC", "base_price": base_price},
        "endpoint_url": f"https://example.com/{name}",
        "stake_eur": stake,
    }


async def _register(client: AsyncClient, did: str, **kwargs) -> dict:
    resp = await client.post("/v1/agents/register", json=_payload(did, **kwargs))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_search_returns_empty_initially(client: AsyncClient) -> None:
    resp = await client.get("/v1/search")
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "matches": []}


@pytest.mark.asyncio
async def test_search_filters_by_capability(client: AsyncClient) -> None:
    await _register(client, "did:agora:e1", name="echo1", capability="Echo")
    await _register(client, "did:agora:t1", name="translator1", capability="LegalTranslation")

    resp = await client.get("/v1/search", params={"capability": "Echo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["matches"][0]["name"] == "echo1"


@pytest.mark.asyncio
async def test_search_hides_probation_by_default(client: AsyncClient) -> None:
    # stake=5.00 -> probation (hidden by default)
    await _register(client, "did:agora:probation_one", stake="5.00")
    await _register(client, "did:agora:new_one", stake="25.00")

    default = (await client.get("/v1/search")).json()
    assert default["total"] == 1
    assert default["matches"][0]["did"] == "did:agora:new_one"

    included = (await client.get("/v1/search", params={"include_probation": "true"})).json()
    assert included["total"] == 2


@pytest.mark.asyncio
async def test_search_filters_by_max_price(client: AsyncClient) -> None:
    await _register(client, "did:agora:cheap", base_price="0.10")
    await _register(client, "did:agora:mid", base_price="1.00")
    await _register(client, "did:agora:expensive", base_price="10.00")

    body = (await client.get("/v1/search", params={"max_price": "1.50"})).json()
    dids = {m["did"] for m in body["matches"]}
    assert dids == {"did:agora:cheap", "did:agora:mid"}


@pytest.mark.asyncio
async def test_search_freetext_on_description(client: AsyncClient) -> None:
    await _register(client, "did:agora:legalbot", description="DE/EN legal translation specialist")
    await _register(client, "did:agora:novel", description="Translates literary fiction")

    body = (await client.get("/v1/search", params={"text": "legal"})).json()
    assert body["total"] == 1
    assert body["matches"][0]["did"] == "did:agora:legalbot"


@pytest.mark.asyncio
async def test_search_min_trust_filter(client: AsyncClient) -> None:
    await _register(client, "did:agora:new_x", stake="25.00")        # new
    await _register(client, "did:agora:verified_x", stake="100.00")  # verified

    body = (await client.get("/v1/search", params={"min_trust": "verified"})).json()
    assert body["total"] == 1
    assert body["matches"][0]["did"] == "did:agora:verified_x"


@pytest.mark.asyncio
async def test_match_endpoint_uses_capability_hint(client: AsyncClient) -> None:
    await _register(client, "did:agora:e2", capability="Echo")
    await _register(client, "did:agora:t2", capability="LegalTranslation")

    resp = await client.post(
        "/v1/match",
        json={"task": "Please echo this back", "capability": "Echo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["matches"][0]["did"] == "did:agora:e2"


@pytest.mark.asyncio
async def test_match_endpoint_falls_back_to_freetext(client: AsyncClient) -> None:
    await _register(
        client,
        "did:agora:legal_match",
        description="Legal document translation DE to EN",
        capability="LegalTranslation",
    )
    await _register(client, "did:agora:other_match", description="Image generation")

    resp = await client.post("/v1/match", json={"task": "legal"})
    body = resp.json()
    dids = {m["did"] for m in body["matches"]}
    assert "did:agora:legal_match" in dids
    assert "did:agora:other_match" not in dids


@pytest.mark.asyncio
async def test_capabilities_taxonomy(client: AsyncClient) -> None:
    body = (await client.get("/v1/capabilities")).json()
    names = {c["name"] for c in body["capabilities"]}
    assert {"Translation", "Verification", "Echo"} <= names
