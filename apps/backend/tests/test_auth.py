"""Tests for Privy auth + user-related routes (Sprint 10d).

Covers:
* /v1/auth/sync upserts a user + personal agent.
* /v1/auth/me returns the logged-in user.
* Missing or malformed bearer tokens are rejected (401).
* /v1/auth/my-listings filters listings to the logged-in user.

The backend's privy verifier has a dev escape hatch: when PRIVY_APP_ID
is empty (which it is in tests), tokens of the form
`agora-dev:<privy_user_id>` are accepted. These tests rely on that.
"""

from __future__ import annotations

from httpx import AsyncClient


def _dev_bearer(uid: str) -> dict[str, str]:
    return {"Authorization": f"Bearer agora-dev:{uid}"}


async def test_sync_creates_user_and_agent(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/auth/sync",
        json={"email": "alice@example.com", "primary_wallet": "0xabc"},
        headers=_dev_bearer("user-alice"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["primary_wallet"] == "0xabc"
    assert body["did"].startswith("did:agora:")
    assert body["agent"] is not None
    assert body["agent"]["did"] == body["did"]
    assert body["agent"]["payout_wallet"] == "0xabc"


async def test_sync_is_idempotent(client: AsyncClient) -> None:
    # First call creates.
    r1 = await client.post(
        "/v1/auth/sync",
        json={"email": "bob@example.com"},
        headers=_dev_bearer("user-bob"),
    )
    did1 = r1.json()["did"]

    # Second call returns the same DID.
    r2 = await client.post(
        "/v1/auth/sync",
        json={"email": "bob@example.com"},
        headers=_dev_bearer("user-bob"),
    )
    did2 = r2.json()["did"]
    assert did1 == did2


async def test_me_returns_logged_in_user(client: AsyncClient) -> None:
    # Need to sync first so the user row exists with full details.
    await client.post(
        "/v1/auth/sync",
        json={"email": "carol@example.com"},
        headers=_dev_bearer("user-carol"),
    )
    r = await client.get("/v1/auth/me", headers=_dev_bearer("user-carol"))
    assert r.status_code == 200
    assert r.json()["email"] == "carol@example.com"


async def test_me_401_without_token(client: AsyncClient) -> None:
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401


async def test_me_401_with_garbage_token(client: AsyncClient) -> None:
    r = await client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer nonsense-not-a-real-token"},
    )
    assert r.status_code == 401


async def test_my_listings_only_returns_owned(client: AsyncClient) -> None:
    # Alice and Bob both sync.
    a = (
        await client.post(
            "/v1/auth/sync",
            json={"email": "alice@example.com", "primary_wallet": "0xaaa"},
            headers=_dev_bearer("user-alice"),
        )
    ).json()
    b = (
        await client.post(
            "/v1/auth/sync",
            json={"email": "bob@example.com", "primary_wallet": "0xbbb"},
            headers=_dev_bearer("user-bob"),
        )
    ).json()

    # Alice publishes a listing.
    listing_payload = {
        "listing_type": "digital_product",
        "title": "Alice's Prompt Pack",
        "description": "Tested prompts.",
        "category": "prompts",
        "tags": ["prompt"],
        "price_amount": "1.50",
        "digital_content_type": "text/markdown",
        "digital_content": {"text": "# Prompts\n..."},
    }
    r = await client.post(
        "/v1/listings", json=listing_payload, headers=_dev_bearer("user-alice")
    )
    assert r.status_code == 201, r.text
    assert r.json()["seller_did"] == a["did"]

    # Alice sees her listing, Bob sees nothing.
    ra = await client.get("/v1/auth/my-listings", headers=_dev_bearer("user-alice"))
    rb = await client.get("/v1/auth/my-listings", headers=_dev_bearer("user-bob"))
    assert ra.status_code == 200
    assert rb.status_code == 200
    assert ra.json()["total"] == 1
    assert rb.json()["total"] == 0
    # Sanity: bob exists but owns nothing.
    assert b["did"] != a["did"]


async def test_create_listing_forces_authed_seller(client: AsyncClient) -> None:
    """An authed caller cannot create a listing under someone else's DID.

    The seller_did field in the body is silently ignored — the API forces
    it to the authenticated user's DID.
    """
    await client.post(
        "/v1/auth/sync",
        json={"email": "dora@example.com", "primary_wallet": "0xddd"},
        headers=_dev_bearer("user-dora"),
    )
    payload = {
        "seller_kind": "user",
        "seller_did": "did:agora:NOT_DORAS_DID",  # should be overridden
        "listing_type": "digital_product",
        "title": "Spoof attempt",
        "description": "Should belong to dora regardless of body",
        "category": "prompts",
        "tags": [],
        "price_amount": "0.50",
        "digital_content_type": "text/plain",
        "digital_content": {"text": "hi"},
    }
    r = await client.post(
        "/v1/listings", json=payload, headers=_dev_bearer("user-dora")
    )
    assert r.status_code == 201, r.text
    me = (await client.get("/v1/auth/me", headers=_dev_bearer("user-dora"))).json()
    assert r.json()["seller_did"] == me["did"]


async def test_anonymous_create_requires_seller_fields(client: AsyncClient) -> None:
    """Anonymous create_listing must explicitly supply all seller fields.

    Calls without auth and without seller_kind/seller_did/payout_wallet
    must 400 — the API can't infer who's selling. Authed callers are
    handled in test_create_listing_forces_authed_seller.
    """
    payload = {
        "listing_type": "digital_product",
        "title": "Missing seller fields",
        "description": "",
        "category": "prompts",
        "tags": [],
        "price_amount": "0.50",
        "digital_content_type": "text/plain",
        "digital_content": {"text": "hi"},
    }
    r = await client.post("/v1/listings", json=payload)
    assert r.status_code == 400, r.text


async def test_archive_blocked_for_non_owner(client: AsyncClient) -> None:
    # Alice publishes.
    await client.post(
        "/v1/auth/sync",
        json={"email": "alice@example.com", "primary_wallet": "0xaaa"},
        headers=_dev_bearer("user-alice"),
    )
    await client.post(
        "/v1/auth/sync",
        json={"email": "mallory@example.com", "primary_wallet": "0xmmm"},
        headers=_dev_bearer("user-mallory"),
    )
    cr = await client.post(
        "/v1/listings",
        json={
            "listing_type": "digital_product",
            "title": "Alice's other thing",
            "description": "",
            "category": "prompts",
            "tags": [],
            "price_amount": "0.50",
            "digital_content_type": "text/plain",
            "digital_content": {"text": "hi"},
        },
        headers=_dev_bearer("user-alice"),
    )
    assert cr.status_code == 201
    lid = cr.json()["id"]

    # Mallory tries to archive Alice's listing → 403.
    r = await client.delete(
        f"/v1/listings/{lid}", headers=_dev_bearer("user-mallory")
    )
    assert r.status_code == 403

    # Anonymous → 401.
    r2 = await client.delete(f"/v1/listings/{lid}")
    assert r2.status_code == 401

    # Alice herself → 200.
    r3 = await client.delete(f"/v1/listings/{lid}", headers=_dev_bearer("user-alice"))
    assert r3.status_code == 200
