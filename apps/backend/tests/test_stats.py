"""Tests for /v1/stats."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient


def _register(did: str, name: str, stake: str = "25") -> dict:
    return {
        "did_document": {"id": did, "verificationMethod": []},
        "name": name,
        "description": "test",
        "owner_did": did,
        "capabilities": [{"type": "Echo"}],
        "pricing": {"model": "per_request", "currency": "EURC", "base_price": "1.00"},
        "endpoint_url": f"https://example.com/{name}",
        "stake_eur": stake,
    }


@pytest.mark.asyncio
async def test_stats_empty(client: AsyncClient) -> None:
    body = (await client.get("/v1/stats")).json()
    assert body["agents"]["total_active"] == 0
    assert body["jobs"]["total"] == 0
    assert body["reviews"]["total"] == 0
    assert Decimal(body["ledger"]["platform_revenue"]) == Decimal("0")


@pytest.mark.asyncio
async def test_stats_after_full_lifecycle(client: AsyncClient) -> None:
    await client.post("/v1/agents/register", json=_register("did:agora:a1", "a1"))
    await client.post("/v1/agents/register", json=_register("did:agora:a2", "a2"))
    await client.post(
        "/v1/jobs/_admin/deposit", json={"agent_did": "did:agora:a1", "amount": "500"}
    )

    job = await client.post(
        "/v1/jobs",
        json={
            "requester_did": "did:agora:a1",
            "provider_did": "did:agora:a2",
            "task": {},
            "budget": "100",
        },
    )
    jid = job.json()["id"]
    await client.post(f"/v1/jobs/{jid}/accept")
    await client.post(f"/v1/jobs/{jid}/result", json={"result": {"ok": True}})
    await client.post(f"/v1/jobs/{jid}/approve")
    await client.post(
        "/v1/reviews",
        json={
            "job_id": jid,
            "reviewer_did": "did:agora:a1",
            "scores": {
                "accuracy": 5,
                "speed": 5,
                "cost": 5,
                "reliability": 5,
                "communication": 5,
            },
        },
    )

    body = (await client.get("/v1/stats")).json()
    assert body["agents"]["total_active"] == 2
    assert body["jobs"]["total"] == 1
    assert body["jobs"]["completed"] == 1
    assert body["reviews"]["total"] == 1
    # 1 EUR Fee, 90% Platform / 10% Insurance
    assert Decimal(body["ledger"]["platform_revenue"]) == Decimal("0.90")
    assert Decimal(body["ledger"]["insurance_pool"]) == Decimal("0.10")
    assert Decimal(body["ledger"]["total_in_escrow"]) == Decimal("0")
