"""Job lifecycle persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Job, JobStatus


async def get(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.get(Job, job_id)


async def find_by_escrow_tx(session: AsyncSession, tx_hash: str) -> Job | None:
    """Look up a job by on-chain escrow transaction hash (idempotency key)."""
    stmt = select(Job).where(Job.escrow_tx_hash == tx_hash)
    return (await session.execute(stmt)).scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    requester: Agent,
    provider: Agent,
    task_spec: dict[str, Any],
    price_amount: Decimal,
    price_currency: str = "EURC",
    deadline: datetime | None = None,
) -> Job:
    job = Job(
        requester_agent_id=requester.id,
        provider_agent_id=provider.id,
        task_spec=task_spec,
        price_amount=price_amount,
        price_currency=price_currency,
        status=JobStatus.offered,
        deadline=deadline,
    )
    session.add(job)
    await session.flush()
    return job


async def list_for_provider(
    session: AsyncSession,
    provider_did: str,
    *,
    status: JobStatus | None = None,
    limit: int = 100,
) -> list[Job]:
    stmt = (
        select(Job)
        .join(Agent, Agent.id == Job.provider_agent_id)
        .where(Agent.did == provider_did)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Job.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_for_requester(
    session: AsyncSession,
    requester_did: str,
    *,
    status: JobStatus | None = None,
    limit: int = 100,
) -> list[Job]:
    stmt = (
        select(Job)
        .join(Agent, Agent.id == Job.requester_agent_id)
        .where(Agent.did == requester_did)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(Job.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ─── State transitions ─────────────────────────────────────


_VALID_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.offered: {JobStatus.accepted, JobStatus.cancelled, JobStatus.refunded},
    JobStatus.accepted: {JobStatus.in_progress, JobStatus.submitted, JobStatus.disputed},
    JobStatus.in_progress: {JobStatus.submitted, JobStatus.disputed},
    JobStatus.submitted: {JobStatus.completed, JobStatus.disputed},
    JobStatus.disputed: {JobStatus.completed, JobStatus.refunded},
    JobStatus.completed: set(),
    JobStatus.cancelled: set(),
    JobStatus.refunded: set(),
}


class IllegalTransition(Exception):
    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"cannot transition job from {current.value} to {target.value}")
        self.current = current
        self.target = target


async def transition(session: AsyncSession, job: Job, target: JobStatus) -> Job:
    allowed = _VALID_TRANSITIONS.get(job.status, set())
    if target not in allowed:
        raise IllegalTransition(job.status, target)
    job.status = target
    if target == JobStatus.completed:
        job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job


async def set_result(session: AsyncSession, job: Job, result: dict[str, Any]) -> Job:
    job.result = result
    await session.flush()
    return job


def to_public_dict(job: Job, requester_did: str, provider_did: str) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "requester_did": requester_did,
        "provider_did": provider_did,
        "task_spec": job.task_spec or {},
        "status": job.status.value,
        "price_amount": str(job.price_amount),
        "price_currency": job.price_currency,
        "result": job.result,
        "deadline": job.deadline.isoformat() if job.deadline else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }
