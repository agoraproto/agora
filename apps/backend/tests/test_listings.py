"""Tests for the marketplace listings API (Sprint 10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


def _agent_payload(did: str = "did:agora:seller_a") -> dict:
    """Used to register an agent that can then become a seller."""
    return {
        "did_document": {"id": did, "verificationMethod": []},
        "name": "seller-agent",
        "description": "An agent that sells things.",
        "owner_did": did,
        "capabilities": [{"type": "Echo"}],
        "pricing": {"model": "per_request", "currency": "USDC", "base_price": "0.50"},
        "endpoint_url": "https://example.com/echo",
        "stake_eur": "25.00",
    }


def _service_listing(seller_did: str) -> dict:
    return {
        "seller_kind": "agent",
        "seller_did": seller_did,
        "payout_wallet": "0x" + "9" * 40,
        "listing_type": "service",
        "title": "Test translation service",
        "description": "Drop-in EN→DE translation.",
        "category": "translation",
        "tags": ["en", "de"],
        "price_amount": "0.80",
        "service_capability": "Translation",
        "service_input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    }


def _product_listing(seller_did: str = "did:agora:human_seller_x") -> dict:
    return {
        "seller_kind": "user",
        "seller_did": seller_did,
        "payout_wallet": "0x" + "a" * 40,
        "listing_type": "digital_product",
        "title": "Prompt pack",
        "description": "A pack of useful prompts.",
        "category": "prompts",
        "tags": ["prompts"],
        "price_amount": "1.50",
        "digital_content_type": "text/markdown",
        "digital_content": {"filename": "pack.md", "text": "..."},
    }


@pytest.mark.asyncio
async def test_create_service_listing(client: AsyncClient) -> None:
    # Seller must exist as an agent first.
    reg = await client.post("/v1/agents/register", json=_agent_payload("did:agora:seller_a"))
    assert reg.status_code == 201

    r = await client.post("/v1/listings", json=_service_listing("did:agora:seller_a"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["listing_type"] == "service"
    assert body["status"] == "active"
    assert body["service_capability"] == "Translation"
    assert body["price_amount"] == "0.800000"  # Numeric(18,6) repr
    # digital_content must NOT be exposed for services (it's None).
    assert body["digital_content_type"] is None


@pytest.mark.asyncio
async def test_create_digital_product_listing(client: AsyncClient) -> None:
    r = await client.post("/v1/listings", json=_product_listing())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["listing_type"] == "digital_product"
    assert body["digital_content_type"] == "text/markdown"
    # CRITICAL: the actual deliverable must NOT leak in the public response.
    assert "digital_content" not in body or body.get("digital_content") is None, (
        "digital_content must be hidden from public dict — it's the paid deliverable"
    )


@pytest.mark.asyncio
async def test_service_listing_requires_capability(client: AsyncClient) -> None:
    await client.post("/v1/agents/register", json=_agent_payload("did:agora:seller_b"))
    payload = _service_listing("did:agora:seller_b")
    payload["service_capability"] = None
    r = await client.post("/v1/listings", json=payload)
    assert r.status_code == 400
    assert "service_capability" in r.json()["detail"]


@pytest.mark.asyncio
async def test_digital_product_listing_requires_content(client: AsyncClient) -> None:
    payload = _product_listing()
    payload["digital_content"] = None
    r = await client.post("/v1/listings", json=payload)
    assert r.status_code == 400
    assert "digital_content" in r.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_agent_seller_rejected(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/listings", json=_service_listing("did:agora:does_not_exist")
    )
    assert r.status_code == 400
    assert "not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_list_with_filters(client: AsyncClient) -> None:
    await client.post("/v1/agents/register", json=_agent_payload("did:agora:seller_c"))
    # one service, one product
    await client.post("/v1/listings", json=_service_listing("did:agora:seller_c"))
    await client.post("/v1/listings", json=_product_listing())

    # No filters — both listings
    r = await client.get("/v1/listings")
    assert r.status_code == 200
    assert r.json()["total"] >= 2

    # listing_type filter
    r = await client.get("/v1/listings", params={"listing_type": "service"})
    assert r.status_code == 200
    body = r.json()
    assert all(L["listing_type"] == "service" for L in body["listings"])

    # category filter
    r = await client.get("/v1/listings", params={"category": "prompts"})
    body = r.json()
    assert all(L["category"] == "prompts" for L in body["listings"])

    # seller_kind filter
    r = await client.get("/v1/listings", params={"seller_kind": "user"})
    body = r.json()
    assert all(L["seller_kind"] == "user" for L in body["listings"])

    # max_price filter
    r = await client.get("/v1/listings", params={"max_price": "1.00"})
    body = r.json()
    # Service at 0.80 should appear; product at 1.50 shouldn't.
    assert all(float(L["price_amount"]) <= 1.0 for L in body["listings"])


@pytest.mark.asyncio
async def test_free_text_search(client: AsyncClient) -> None:
    await client.post("/v1/listings", json=_product_listing())
    r = await client.get("/v1/listings", params={"q": "Prompt"})
    body = r.json()
    assert body["total"] >= 1
    assert any("prompt" in L["title"].lower() for L in body["listings"])


@pytest.mark.asyncio
async def test_get_by_id(client: AsyncClient) -> None:
    created = (await client.post("/v1/listings", json=_product_listing())).json()
    r = await client.get(f"/v1/listings/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_404_on_unknown_id(client: AsyncClient) -> None:
    r = await client.get("/v1/listings/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_400_on_bad_uuid(client: AsyncClient) -> None:
    r = await client.get("/v1/listings/not-a-uuid")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_archive(client: AsyncClient) -> None:
    created = (await client.post("/v1/listings", json=_product_listing())).json()
    r = await client.delete(f"/v1/listings/{created['id']}")
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    # Default browse hides archived listings.
    browse = await client.get("/v1/listings")
    ids_in_browse = {L["id"] for L in browse.json()["listings"]}
    assert created["id"] not in ids_in_browse


@pytest.mark.asyncio
async def test_invalid_price_rejected(client: AsyncClient) -> None:
    payload = _product_listing()
    payload["price_amount"] = "-1.00"
    r = await client.post("/v1/listings", json=payload)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bad_seller_kind_rejected(client: AsyncClient) -> None:
    payload = _product_listing()
    payload["seller_kind"] = "bot"
    r = await client.post("/v1/listings", json=payload)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_pagination(client: AsyncClient) -> None:
    # Create 5 product listings.
    for i in range(5):
        p = _product_listing(f"did:agora:human_seller_{i}")
        p["title"] = f"Pack {i}"
        await client.post("/v1/listings", json=p)
    # limit=2 returns at most 2
    r = await client.get("/v1/listings", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()["listings"]) <= 2
