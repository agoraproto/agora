"""Tests for reviews, reputation aggregation, and Stage-1 code-as-judge."""

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


async def _deposit(client: AsyncClient, did: str, amount: str) -> None:
    resp = await client.post(
        "/v1/jobs/_admin/deposit", json={"agent_did": did, "amount": amount}
    )
    assert resp.status_code == 201, resp.text


async def _complete_job(
    client: AsyncClient,
    requester_did: str,
    provider_did: str,
    budget: str = "100",
    task: dict | None = None,
) -> str:
    """Run a job through to completed and return its id."""
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": requester_did,
            "provider_did": provider_did,
            "task": task or {},
            "budget": budget,
        },
    )
    job_id = create.json()["id"]
    await client.post(f"/v1/jobs/{job_id}/accept")
    await client.post(f"/v1/jobs/{job_id}/result", json={"result": {"echoed": "ok"}})
    await client.post(f"/v1/jobs/{job_id}/approve")
    return job_id


_FIVE_STAR = {
    "accuracy": 5,
    "speed": 5,
    "cost": 5,
    "reliability": 5,
    "communication": 5,
}


@pytest.mark.asyncio
async def test_submit_review_after_completed_job(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")

    job_id = await _complete_job(client, "did:agora:alice", "did:agora:bob")

    resp = await client.post(
        "/v1/reviews",
        json={
            "job_id": job_id,
            "reviewer_did": "did:agora:alice",
            "scores": _FIVE_STAR,
            "comment": "great work",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["reviewee_did"] == "did:agora:bob"
    assert body["aggregate"] == "5.00"
    assert body["reviewee_reputation"] == "5.00"
    assert body["reviewee_reputation_count"] == 1


@pytest.mark.asyncio
async def test_cannot_review_non_completed_job(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "50")
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": "did:agora:alice",
            "provider_did": "did:agora:bob",
            "task": {},
            "budget": "10",
        },
    )
    job_id = create.json()["id"]

    resp = await client.post(
        "/v1/reviews",
        json={"job_id": job_id, "reviewer_did": "did:agora:alice", "scores": _FIVE_STAR},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reviewer_must_be_party(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _register(client, "did:agora:eve", name="eve")
    await _deposit(client, "did:agora:alice", "200")
    job_id = await _complete_job(client, "did:agora:alice", "did:agora:bob")

    resp = await client.post(
        "/v1/reviews",
        json={"job_id": job_id, "reviewer_did": "did:agora:eve", "scores": _FIVE_STAR},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_review_rejected(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")
    job_id = await _complete_job(client, "did:agora:alice", "did:agora:bob")

    first = await client.post(
        "/v1/reviews",
        json={"job_id": job_id, "reviewer_did": "did:agora:alice", "scores": _FIVE_STAR},
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/reviews",
        json={"job_id": job_id, "reviewer_did": "did:agora:alice", "scores": _FIVE_STAR},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_invalid_scores_rejected(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")
    job_id = await _complete_job(client, "did:agora:alice", "did:agora:bob")

    # Out of range
    bad = await client.post(
        "/v1/reviews",
        json={
            "job_id": job_id,
            "reviewer_did": "did:agora:alice",
            "scores": {**_FIVE_STAR, "accuracy": 10},
        },
    )
    assert bad.status_code == 400

    # Missing dimension
    missing = await client.post(
        "/v1/reviews",
        json={
            "job_id": job_id,
            "reviewer_did": "did:agora:alice",
            "scores": {"accuracy": 5, "speed": 5},
        },
    )
    assert missing.status_code == 400


@pytest.mark.asyncio
async def test_reputation_aggregates_multiple_reviews(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "1000")

    # 3 jobs, 3 reviews with averages 5.0, 3.0, 4.0 -> mean 4.00
    job1 = await _complete_job(client, "did:agora:alice", "did:agora:bob", budget="100")
    job2 = await _complete_job(client, "did:agora:alice", "did:agora:bob", budget="100")
    job3 = await _complete_job(client, "did:agora:alice", "did:agora:bob", budget="100")

    await client.post(
        "/v1/reviews",
        json={
            "job_id": job1,
            "reviewer_did": "did:agora:alice",
            "scores": _FIVE_STAR,
        },
    )
    await client.post(
        "/v1/reviews",
        json={
            "job_id": job2,
            "reviewer_did": "did:agora:alice",
            "scores": {k: 3 for k in _FIVE_STAR},
        },
    )
    await client.post(
        "/v1/reviews",
        json={
            "job_id": job3,
            "reviewer_did": "did:agora:alice",
            "scores": {k: 4 for k in _FIVE_STAR},
        },
    )

    rep = (await client.get("/v1/agents/did:agora:bob/reputation")).json()
    assert rep["count"] == 3
    assert Decimal(rep["score"]) == Decimal("4.00")


@pytest.mark.asyncio
async def test_auto_promote_to_verified_after_5_jobs_and_4_plus(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "1000")

    # 5 completed jobs with 5-star reviews
    for _ in range(5):
        jid = await _complete_job(client, "did:agora:alice", "did:agora:bob", budget="50")
        await client.post(
            "/v1/reviews",
            json={"job_id": jid, "reviewer_did": "did:agora:alice", "scores": _FIVE_STAR},
        )

    rep = (await client.get("/v1/agents/did:agora:bob/reputation")).json()
    assert rep["jobs_completed"] == 5
    assert rep["trust_level"] == "verified"  # promoted from "new"


@pytest.mark.asyncio
async def test_dispute_echo_matches_resolves_for_provider(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")

    # Create job with echo-type task
    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": "did:agora:alice",
            "provider_did": "did:agora:bob",
            "task": {"type": "Echo", "prompt": "hello"},
            "budget": "50",
        },
    )
    job_id = create.json()["id"]
    await client.post(f"/v1/jobs/{job_id}/accept")
    await client.post(
        f"/v1/jobs/{job_id}/result", json={"result": {"echoed": "hello"}}
    )
    # Requester disputes anyway
    resp = await client.post(
        f"/v1/jobs/{job_id}/dispute",
        json={"reason": "I think the echo is wrong", "evidence": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Stage-1 judge sees echoed == prompt -> for provider; job completes, ledger releases
    assert body["dispute"]["status"] == "resolved_for_provider"
    assert body["job_status"] == "completed"


@pytest.mark.asyncio
async def test_dispute_echo_mismatch_resolves_for_requester(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")

    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": "did:agora:alice",
            "provider_did": "did:agora:bob",
            "task": {"type": "Echo", "prompt": "hello"},
            "budget": "50",
        },
    )
    job_id = create.json()["id"]
    await client.post(f"/v1/jobs/{job_id}/accept")
    await client.post(
        f"/v1/jobs/{job_id}/result", json={"result": {"echoed": "WRONG"}}
    )

    resp = await client.post(
        f"/v1/jobs/{job_id}/dispute",
        json={"reason": "bad echo", "evidence": {}},
    )
    body = resp.json()
    assert body["dispute"]["status"] == "resolved_for_requester"
    assert body["job_status"] == "refunded"

    # Alice was refunded fully
    bal = (await client.get("/v1/jobs/_admin/balance/did:agora:alice")).json()
    assert Decimal(bal["available"]) == Decimal("200")
    assert Decimal(bal["in_escrow"]) == Decimal("0")


@pytest.mark.asyncio
async def test_dispute_no_deterministic_check_escalates(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")

    create = await client.post(
        "/v1/jobs",
        json={
            "requester_did": "did:agora:alice",
            "provider_did": "did:agora:bob",
            "task": {"type": "Translation", "prompt": "Hallo Welt"},
            "budget": "50",
        },
    )
    job_id = create.json()["id"]
    await client.post(f"/v1/jobs/{job_id}/accept")
    await client.post(
        f"/v1/jobs/{job_id}/result", json={"result": {"text": "Hello World"}}
    )
    resp = await client.post(
        f"/v1/jobs/{job_id}/dispute",
        json={"reason": "not literal enough", "evidence": {}},
    )
    body = resp.json()
    assert body["dispute"]["status"] == "escalated"
    assert body["job_status"] == "disputed"


@pytest.mark.asyncio
async def test_list_reviews_for_agent(client: AsyncClient) -> None:
    await _register(client, "did:agora:alice", name="alice")
    await _register(client, "did:agora:bob", name="bob")
    await _deposit(client, "did:agora:alice", "200")
    job_id = await _complete_job(client, "did:agora:alice", "did:agora:bob")
    await client.post(
        "/v1/reviews",
        json={"job_id": job_id, "reviewer_did": "did:agora:alice", "scores": _FIVE_STAR, "comment": "ok"},
    )
    body = (await client.get("/v1/agents/did:agora:bob/reviews")).json()
    assert body["total"] == 1
    assert body["reviews"][0]["aggregate"] == "5.00"
    assert body["reviews"][0]["comment"] == "ok"
