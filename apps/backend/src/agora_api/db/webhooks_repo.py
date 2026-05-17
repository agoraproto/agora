"""Persistence for outbound webhook deliveries (Sprint 6 / ADR 008)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import WebhookDelivery, WebhookDeliveryStatus

# Retry schedule (seconds after the previous attempt). After max_attempts the
# row is marked `exhausted`. Total time spent retrying: ~31h.
_RETRY_BACKOFF_SECONDS = (30, 120, 600, 3600, 21600, 86400)


def next_retry_delay(attempt_count: int) -> int:
    """Delay in seconds before the next attempt, given how many attempts have failed."""
    idx = max(0, attempt_count - 1)
    if idx >= len(_RETRY_BACKOFF_SECONDS):
        return _RETRY_BACKOFF_SECONDS[-1]
    return _RETRY_BACKOFF_SECONDS[idx]


async def enqueue(
    session: AsyncSession,
    *,
    agent_did: str,
    agent_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
    event_type: str,
    endpoint_url: str,
    payload: dict[str, Any],
) -> WebhookDelivery:
    """Create a pending delivery, due immediately."""
    delivery = WebhookDelivery(
        agent_did=agent_did,
        agent_id=agent_id,
        job_id=job_id,
        event_type=event_type,
        endpoint_url=endpoint_url,
        payload=payload,
        status=WebhookDeliveryStatus.pending,
        attempt_count=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def claim_due(
    session: AsyncSession, *, batch_size: int = 10
) -> list[WebhookDelivery]:
    """Atomically claim up to `batch_size` deliveries that are due now.

    Strategy: SELECT candidate ids, then UPDATE...WHERE status='pending' AND id
    IN (...) RETURNING. SQLite doesn't support RETURNING for UPDATE on all
    versions, so we use a select-then-update with the optimistic race that
    the worker is the only writer (true in our single-instance bootstrap).
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == WebhookDeliveryStatus.pending,
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(batch_size)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if not rows:
        return []
    ids = [r.id for r in rows]
    await session.execute(
        update(WebhookDelivery)
        .where(WebhookDelivery.id.in_(ids))
        .values(status=WebhookDeliveryStatus.delivering, last_attempt_at=now)
    )
    await session.flush()
    return rows


async def mark_delivered(
    session: AsyncSession, delivery: WebhookDelivery, *, response_status: int
) -> None:
    now = datetime.now(timezone.utc)
    delivery.status = WebhookDeliveryStatus.delivered
    delivery.attempt_count += 1
    delivery.last_attempt_at = now
    delivery.delivered_at = now
    delivery.last_response_status = response_status
    delivery.last_error = None
    await session.flush()


async def mark_failed_retry(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    response_status: int | None,
    error: str,
    max_attempts: int,
) -> None:
    """Mark a failed attempt; schedule retry or mark exhausted if out of budget."""
    now = datetime.now(timezone.utc)
    delivery.attempt_count += 1
    delivery.last_attempt_at = now
    delivery.last_response_status = response_status
    delivery.last_error = error[:1000] if error else None

    if delivery.attempt_count >= max_attempts:
        delivery.status = WebhookDeliveryStatus.exhausted
    else:
        delay = next_retry_delay(delivery.attempt_count)
        delivery.next_attempt_at = now + timedelta(seconds=delay)
        delivery.status = WebhookDeliveryStatus.pending
    await session.flush()


async def mark_permanently_failed(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    response_status: int | None,
    error: str,
) -> None:
    """A non-retryable failure (e.g. 4xx that isn't 408/429). Burn the budget."""
    now = datetime.now(timezone.utc)
    delivery.attempt_count += 1
    delivery.last_attempt_at = now
    delivery.last_response_status = response_status
    delivery.last_error = error[:1000] if error else None
    delivery.status = WebhookDeliveryStatus.failed
    await session.flush()


async def list_for_agent(
    session: AsyncSession,
    agent_did: str,
    *,
    limit: int = 50,
) -> list[WebhookDelivery]:
    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.agent_did == agent_did)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def to_public_dict(d: WebhookDelivery) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "agent_did": d.agent_did,
        "job_id": str(d.job_id) if d.job_id else None,
        "event_type": d.event_type,
        "endpoint_url": d.endpoint_url,
        "status": d.status.value,
        "attempt_count": d.attempt_count,
        "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
        "last_attempt_at": d.last_attempt_at.isoformat() if d.last_attempt_at else None,
        "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
        "last_response_status": d.last_response_status,
        "last_error": d.last_error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
