"""Webhook delivery worker — happy path, retries, exhaustion."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from agora_api.db import webhooks_repo
from agora_api.db.models import WebhookDelivery, WebhookDeliveryStatus
from agora_api.webhooks import delivery as worker_module
from agora_api.webhooks.delivery import process_batch
from agora_api.webhooks.signing import (
    SignatureInvalid,
    get_signer,
    verify_signature,
)


@pytest.fixture(autouse=True)
def _reset_signer() -> None:
    get_signer.cache_clear()


async def _make_delivery(session, *, endpoint: str = "http://provider.local/hook") -> WebhookDelivery:
    d = await webhooks_repo.enqueue(
        session,
        agent_did="did:agora:provider",
        agent_id=None,
        job_id=None,
        event_type="job.offered",
        endpoint_url=endpoint,
        payload={"job_id": "abc", "price": "5"},
    )
    await session.commit()
    return d


def _install_mock_transport(monkeypatch, responder):
    """Replace httpx.AsyncClient with one bound to a MockTransport."""
    transport = httpx.MockTransport(responder)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


async def test_delivery_happy_path(session, monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"ok": True})

    _install_mock_transport(monkeypatch, handler)
    await _make_delivery(session)

    n = await process_batch()
    assert n == 1

    # Re-fetch
    from sqlalchemy import select
    rows = (await session.execute(select(WebhookDelivery))).scalars().all()
    assert len(rows) == 1
    d = rows[0]
    assert d.status == WebhookDeliveryStatus.delivered
    assert d.attempt_count == 1
    assert d.last_response_status == 200

    # The body the worker sent must verify against Agora's pubkey.
    pub = get_signer().public_key_b64
    sig = captured["headers"]["x-agora-signature"]
    ts = captured["headers"]["x-agora-timestamp"]
    verify_signature(pub, sig, ts, captured["body"])

    # Canonical encoding: sorted keys, no spaces.
    assert json.loads(captured["body"]) == {"job_id": "abc", "price": "5"}


async def test_delivery_retries_on_5xx(session, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="overloaded")

    _install_mock_transport(monkeypatch, handler)
    await _make_delivery(session)

    n = await process_batch()
    assert n == 1

    from sqlalchemy import select
    d = (await session.execute(select(WebhookDelivery))).scalar_one()
    assert d.status == WebhookDeliveryStatus.pending  # back to pending for retry
    assert d.attempt_count == 1
    assert d.last_response_status == 503
    now = datetime.now(timezone.utc).replace(tzinfo=None) if d.next_attempt_at.tzinfo is None else datetime.now(timezone.utc)
    assert d.next_attempt_at > now + timedelta(seconds=10)


async def test_delivery_permanent_failure_on_4xx(session, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such endpoint")

    _install_mock_transport(monkeypatch, handler)
    await _make_delivery(session)
    await process_batch()

    from sqlalchemy import select
    d = (await session.execute(select(WebhookDelivery))).scalar_one()
    assert d.status == WebhookDeliveryStatus.failed
    assert d.attempt_count == 1


async def test_delivery_exhausts_after_max_attempts(session, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _install_mock_transport(monkeypatch, handler)
    await _make_delivery(session)

    from sqlalchemy import select
    # Drive the worker up to max_attempts. After each failed try the
    # next_attempt_at is in the future, so we need to fast-forward it manually
    # to keep the worker picking up the same row.
    for _ in range(6):  # webhook_max_attempts = 6 default
        session.expire_all()
        d = (await session.execute(select(WebhookDelivery))).scalar_one()
        if d.status == WebhookDeliveryStatus.exhausted:
            break
        # rewind next_attempt_at so the row is due again
        d.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
        await process_batch()

    session.expire_all()
    d = (await session.execute(select(WebhookDelivery))).scalar_one()
    assert d.status == WebhookDeliveryStatus.exhausted
    assert d.attempt_count == 6


async def test_enqueue_skips_when_no_endpoint(session) -> None:
    """enqueue_for_agent should be a no-op when the agent has no endpoint."""
    from agora_api.db.agents_repo import create as create_agent
    from decimal import Decimal

    agent, _secret = await create_agent(
        session,
        did="did:agora:no-endpoint",
        did_document={"id": "did:agora:no-endpoint"},
        name="quiet",
        description="",
        owner_did="did:agora:no-endpoint",
        capabilities=[{"type": "Echo"}],
        pricing={"base_price": "1"},
        endpoint_url="",  # <- empty
        stake_eur=Decimal("25"),
        sponsor_did=None,
        sponsor_signature=None,
    )
    await session.commit()

    result = await worker_module.enqueue_for_agent(
        session,
        agent=agent,
        job_id=None,
        event_type="job.offered",
        payload={"x": 1},
    )
    assert result is None
