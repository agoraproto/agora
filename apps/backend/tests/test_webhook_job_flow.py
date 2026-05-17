"""End-to-end: job lifecycle transitions enqueue the right webhooks."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from agora_api.db.agents_repo import create as create_agent
from agora_api.db.ledger_repo import deposit
from agora_api.db.models import WebhookDelivery


async def _register_pair(client) -> tuple[str, str]:
    """Create requester (no endpoint) + provider (with endpoint). Return DIDs."""
    requester_payload = {
        "did_document": {"id": "did:agora:req-1"},
        "name": "requester",
        "owner_did": "did:agora:req-1",
        "capabilities": [{"type": "Generic"}],
        "pricing": {"base_price": "0"},
        "endpoint_url": "",
        "stake_eur": "25.00",
    }
    provider_payload = {
        "did_document": {"id": "did:agora:prov-1"},
        "name": "provider",
        "owner_did": "did:agora:prov-1",
        "capabilities": [{"type": "Echo"}],
        "pricing": {"base_price": "1"},
        "endpoint_url": "http://provider.local/hook",
        "stake_eur": "25.00",
    }
    r1 = await client.post("/v1/agents/register", json=requester_payload)
    assert r1.status_code == 201
    r2 = await client.post("/v1/agents/register", json=provider_payload)
    assert r2.status_code == 201
    return "did:agora:req-1", "did:agora:prov-1"


async def _deliveries(session) -> list[WebhookDelivery]:
    rows = (
        await session.execute(
            select(WebhookDelivery).order_by(WebhookDelivery.created_at)
        )
    ).scalars().all()
    return list(rows)


@pytest.mark.asyncio
async def test_job_offered_enqueues_webhook_to_provider(client, session) -> None:
    req_did, prov_did = await _register_pair(client)

    # Fund the requester so escrow holds.
    await deposit(session, req_did, Decimal("50"))
    await session.commit()

    r = await client.post(
        "/v1/jobs",
        json={
            "requester_did": req_did,
            "provider_did": prov_did,
            "task": {"text": "hello"},
            "budget": "5",
        },
    )
    assert r.status_code == 201

    deliveries = await _deliveries(session)
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d.event_type == "job.offered"
    assert d.agent_did == prov_did
    assert d.endpoint_url == "http://provider.local/hook"
    assert d.payload["task"] == {"text": "hello"}


@pytest.mark.asyncio
async def test_full_flow_enqueues_full_webhook_chain(client, session) -> None:
    req_did, prov_did = await _register_pair(client)
    # Give requester an endpoint too so we can see job.accepted webhook
    # (re-register with endpoint via direct DB tweak: in this test we just
    # check provider-side events).
    await deposit(session, req_did, Decimal("50"))
    await session.commit()

    # Create job
    job_resp = await client.post(
        "/v1/jobs",
        json={
            "requester_did": req_did,
            "provider_did": prov_did,
            "task": {"echo": "hi"},
            "budget": "5",
        },
    )
    job_id = job_resp.json()["id"]

    # Provider accepts
    r = await client.post(f"/v1/jobs/{job_id}/accept")
    assert r.status_code == 200

    # Provider submits result
    r = await client.post(
        f"/v1/jobs/{job_id}/result", json={"result": {"echo": "hi"}}
    )
    assert r.status_code == 200

    # Requester approves
    r = await client.post(f"/v1/jobs/{job_id}/approve")
    assert r.status_code == 200

    deliveries = await _deliveries(session)
    types = [d.event_type for d in deliveries]
    # The requester has no endpoint, so job.accepted / job.result_submitted
    # webhooks aimed at the requester are skipped. Provider gets offered +
    # completed.
    assert "job.offered" in types
    assert "job.completed" in types
    # Only deliveries with endpoints were persisted: 2 events to the provider.
    assert all(d.endpoint_url == "http://provider.local/hook" for d in deliveries)
