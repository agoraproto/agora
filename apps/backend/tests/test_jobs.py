"""Tests for the full job lifecycle against an in-memory DB."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient


def _register_payload(did: str, name: str = "agent", stake: str = "25.00") -> dict:
    return {
        "did_document": {"id": did, "verificationMethod": []},
        "name": name,
        "description": "test",
        "owner_did": did,
        "capabilities": [{"type": "Echo"}],
        "pricing": {"model": "per_request", "currency": "EURC", "base_price": "0.50"},
        "endpoint_url": f"https://example.com/{name}",
        "stake_eur": stake,
    }


async def _register(client: AsyncClient, did: str, **kwargs) -> dict:
    resp = await client.post("/v1/agents/register", json=_register_payload(did, **kwargs))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _deposit(client: AsyncClient, did: str, amount: str) -> dict:
    resp = await client.post(
        "/v1/jobs/_admin/deposit", json={"agent_did": did, "amount": amount}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def alice_did() -> str:
    return "did:agora:alice"


@pytest.fixture
def bob_did() -> str:
    return "did:agora:bob"


@pytest.mark.asyncio
async def test_happy_path_offer_accept_result_approve(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    """Alice (requester) hires Bob (provider) for 100 EUR; full success path."""
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "200")

    # Create job
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {"prompt": "echo this"},
            "budget": "100",
        },
    )
    assert create.status_code == 201, create.text
    job_id = create.json()["id"]
    assert create.json()["status"] == "offered"

    # Alice's balance: 200 -> 100 available, 100 in_escrow
    bal = (await client.get(f"/v1/jobs/_admin/balance/{alice_did}")).json()
    assert bal["available"] == "100.000000"
    assert bal["in_escrow"] == "100.000000"

    # Bob accepts
    accept = await client.post(f"/v1/jobs/{job_id}/accept")
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"

    # Bob submits result
    submit = await client.post(
        f"/v1/jobs/{job_id}/result",
        json={"result": {"echoed": "echo this"}},
    )
    assert submit.status_code == 200
    assert submit.json()["status"] == "submitted"

    # Alice approves -> escrow releases with fee split
    approve = await client.post(f"/v1/jobs/{job_id}/approve")
    assert approve.status_code == 200, approve.text
    body = approve.json()
    assert body["status"] == "completed"
    # 100 EUR * 1% = 1 EUR fee
    assert body["fee"] == "1.00"
    assert body["payee_received"] == "99.00"

    # Final balances
    alice_bal = (await client.get(f"/v1/jobs/_admin/balance/{alice_did}")).json()
    bob_bal = (await client.get(f"/v1/jobs/_admin/balance/{bob_did}")).json()
    platform_bal = (
        await client.get("/v1/jobs/_admin/balance/did:agora:platform")
    ).json()
    insurance_bal = (
        await client.get("/v1/jobs/_admin/balance/did:agora:insurance_pool")
    ).json()

    # Alice: 100 left of 200, escrow back to 0
    assert Decimal(alice_bal["available"]) == Decimal("100")
    assert Decimal(alice_bal["in_escrow"]) == Decimal("0")
    # Bob: 99 EUR payout
    assert Decimal(bob_bal["available"]) == Decimal("99")
    # Platform: 0.90, Insurance: 0.10
    assert Decimal(platform_bal["available"]) == Decimal("0.90")
    assert Decimal(insurance_bal["available"]) == Decimal("0.10")


@pytest.mark.asyncio
async def test_create_job_rejects_insufficient_funds(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    # No deposit; alice has zero balance

    resp = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {},
            "budget": "10",
        },
    )
    assert resp.status_code == 402
    assert "insufficient funds" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_job_self_provider_rejected(
    client: AsyncClient, alice_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _deposit(client, alice_did, "50")

    resp = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": alice_did,
            "task": {},
            "budget": "10",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_reject_refunds_escrow(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "100")

    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {},
            "budget": "40",
        },
    )
    job_id = create.json()["id"]
    bal = (await client.get(f"/v1/jobs/_admin/balance/{alice_did}")).json()
    assert Decimal(bal["in_escrow"]) == Decimal("40")

    reject = await client.post(f"/v1/jobs/{job_id}/reject")
    assert reject.status_code == 200
    assert reject.json()["status"] == "cancelled"

    bal_after = (await client.get(f"/v1/jobs/_admin/balance/{alice_did}")).json()
    assert Decimal(bal_after["available"]) == Decimal("100")
    assert Decimal(bal_after["in_escrow"]) == Decimal("0")


@pytest.mark.asyncio
async def test_illegal_transitions_rejected(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "50")
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {},
            "budget": "20",
        },
    )
    job_id = create.json()["id"]
    # Cannot approve before submitted
    resp = await client.post(f"/v1/jobs/{job_id}/approve")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_dispute_pauses_escrow(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "100")
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {},
            "budget": "30",
        },
    )
    job_id = create.json()["id"]
    await client.post(f"/v1/jobs/{job_id}/accept")
    await client.post(
        f"/v1/jobs/{job_id}/result", json={"result": {"data": "bad"}}
    )

    dispute = await client.post(
        f"/v1/jobs/{job_id}/dispute",
        json={"reason": "result is wrong", "evidence": {"hash": "abc"}},
    )
    assert dispute.status_code == 200
    assert dispute.json()["status"] == "disputed"

    # Cannot approve a disputed job
    approve = await client.post(f"/v1/jobs/{job_id}/approve")
    assert approve.status_code == 409


@pytest.mark.asyncio
async def test_list_jobs_by_provider(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "500")
    for _i in range(3):
        await client.post(
            "/v1/jobs",
            json={
                "requester_did": alice_did,
                "provider_did": bob_did,
                "task": {},
                "budget": "50",
            },
        )
    resp = await client.get("/v1/jobs", params={"provider_did": bob_did})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert all(j["provider_did"] == bob_did for j in body["jobs"])


@pytest.mark.asyncio
async def test_get_job_by_id(
    client: AsyncClient, alice_did: str, bob_did: str
) -> None:
    await _register(client, alice_did, name="alice")
    await _register(client, bob_did, name="bob")
    await _deposit(client, alice_did, "100")
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": alice_did,
            "provider_did": bob_did,
            "task": {"x": 1},
            "budget": "10",
        },
    )
    job_id = create.json()["id"]
    fetched = await client.get(f"/v1/jobs/{job_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["id"] == job_id
    assert body["task_spec"] == {"x": 1}
    assert body["status"] == "offered"


@pytest.mark.asyncio
async def test_list_requires_filter(client: AsyncClient) -> None:
    resp = await client.get("/v1/jobs")
    assert resp.status_code == 400
