"""Async webhook delivery worker (Sprint 6 / ADR 008).

A single asyncio task started in FastAPI's lifespan. Polls the DB for due
deliveries, POSTs them with HTTP signed by Agora's Ed25519 key, and updates
the row state. Bootstrap-friendly: no Redis/Celery, just the DB as queue.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any

import httpx

from ..config import get_settings
from ..db import webhooks_repo
from ..db.base import get_sessionmaker
from ..db.models import WebhookDelivery
from ..logging import get_logger
from .signing import sign_body

log = get_logger(__name__)


_PERMANENT_FAILURE_STATUSES = {400, 401, 403, 404, 410, 422}  # 4xx, no retry
_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}  # retry per ADR 008


def _serialize_payload(payload: dict[str, Any]) -> bytes:
    """Canonical JSON encoding used both for signing and for the request body."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def _deliver_one(
    client: httpx.AsyncClient,
    delivery: WebhookDelivery,
    *,
    timeout: float,
) -> tuple[int | None, str | None]:
    """Send one webhook. Return (response_status, error_message)."""
    body = _serialize_payload(delivery.payload or {})
    headers = sign_body(body)
    headers["Content-Type"] = "application/json"
    headers["X-Agora-Event"] = delivery.event_type
    headers["X-Agora-Delivery-Id"] = str(delivery.id)

    try:
        resp = await client.post(
            delivery.endpoint_url,
            content=body,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        )
    except httpx.TimeoutException as e:
        return None, f"timeout: {e}"
    except httpx.RequestError as e:
        return None, f"request_error: {e}"

    if 200 <= resp.status_code < 300:
        return resp.status_code, None
    # Truncate body for logs / DB
    snippet = (resp.text or "")[:500]
    return resp.status_code, f"http {resp.status_code}: {snippet}"


async def process_batch(*, batch_size: int = 10) -> int:
    """Process one batch of due deliveries. Returns count attempted.

    Each delivery runs in its own DB transaction so a failure in one doesn't
    poison the others. Public so tests can drive the worker step-by-step.
    """
    settings = get_settings()
    timeout = settings.webhook_request_timeout_seconds
    max_attempts = settings.webhook_max_attempts

    # Phase 1: claim a batch
    async with get_sessionmaker()() as session:
        claimed = await webhooks_repo.claim_due(session, batch_size=batch_size)
        await session.commit()
        # Snapshot fields we need; the WebhookDelivery objects will get reloaded
        # in fresh sessions per-delivery below.
        snapshots = [(d.id, d.event_type, d.endpoint_url) for d in claimed]

    if not snapshots:
        return 0

    # Phase 2: ship each
    async with httpx.AsyncClient() as client:
        for delivery_id, event_type, _endpoint in snapshots:
            async with get_sessionmaker()() as session:
                # Re-fetch the row so we can mutate it inside its own tx
                from sqlalchemy import select

                row = (
                    await session.execute(
                        select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
                    )
                ).scalar_one_or_none()
                if row is None:
                    log.warning("webhook.delivery.missing", delivery_id=str(delivery_id))
                    continue

                resp_status, err = await _deliver_one(client, row, timeout=timeout)

                if resp_status is not None and 200 <= resp_status < 300:
                    await webhooks_repo.mark_delivered(
                        session, row, response_status=resp_status
                    )
                    log.info(
                        "webhook.delivered",
                        delivery_id=str(row.id),
                        event_name=event_type,
                        agent=row.agent_did,
                        attempt=row.attempt_count,
                        status=resp_status,
                    )
                elif resp_status is not None and resp_status in _PERMANENT_FAILURE_STATUSES:
                    await webhooks_repo.mark_permanently_failed(
                        session, row, response_status=resp_status, error=err or "permanent"
                    )
                    log.warning(
                        "webhook.failed_permanent",
                        delivery_id=str(row.id),
                        event_name=event_type,
                        agent=row.agent_did,
                        status=resp_status,
                        error=err,
                    )
                else:
                    # Retryable status, or network/timeout error
                    await webhooks_repo.mark_failed_retry(
                        session,
                        row,
                        response_status=resp_status,
                        error=err or "unknown",
                        max_attempts=max_attempts,
                    )
                    log.warning(
                        "webhook.failed_retry",
                        delivery_id=str(row.id),
                        event_name=event_type,
                        agent=row.agent_did,
                        attempt=row.attempt_count,
                        status=resp_status,
                        error=err,
                    )

                await session.commit()
    return len(snapshots)


async def worker_loop(stop_event: asyncio.Event) -> None:
    """Main worker loop. Cancel via `stop_event.set()`."""
    settings = get_settings()
    interval = settings.webhook_worker_poll_interval_seconds
    log.info("webhook.worker.start", interval=interval, max_attempts=settings.webhook_max_attempts)
    while not stop_event.is_set():
        try:
            n = await process_batch()
            if n:
                log.debug("webhook.worker.batch", count=n)
        except Exception as e:  # pragma: no cover - last-resort
            log.exception("webhook.worker.crash", error=str(e))
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
    log.info("webhook.worker.stop")


# ─── Convenience helpers used by routes ─────────────────────


async def enqueue_for_agent(
    session,
    *,
    agent,
    job_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any],
) -> WebhookDelivery | None:
    """Enqueue a webhook only if the agent has an endpoint configured."""
    endpoint = (agent.public_endpoint or "").strip()
    if not endpoint:
        log.debug(
            "webhook.skip_no_endpoint",
            agent=agent.did,
            event_name=event_type,
            job_id=str(job_id) if job_id else None,
        )
        return None
    return await webhooks_repo.enqueue(
        session,
        agent_did=agent.did,
        agent_id=agent.id,
        job_id=job_id,
        event_type=event_type,
        endpoint_url=endpoint,
        payload=payload,
    )
