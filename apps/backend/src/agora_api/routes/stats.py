"""Public stats / health-of-the-marketplace endpoint."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import get_session
from ..db.ledger_repo import INSURANCE_DID, PLATFORM_DID
from ..db.models import Agent, AgentStatus, Job, JobStatus, LedgerBalance, Review

router = APIRouter()


@router.get(
    "/stats",
    summary="Public marketplace stats (active agents, jobs, ledger totals).",
)
async def stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    # Active agents
    active_q = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == AgentStatus.active)
    )
    total_agents = int(active_q.scalar() or 0)

    # Jobs by status (returns a list of (status, count) tuples)
    by_status_q = await session.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    by_status: dict[str, int] = {
        (row[0].value if hasattr(row[0], "value") else str(row[0])): int(row[1])
        for row in by_status_q.all()
    }
    total_jobs = sum(by_status.values())
    completed = by_status.get(JobStatus.completed.value, 0)
    disputed = by_status.get(JobStatus.disputed.value, 0)

    # Reviews
    reviews_q = await session.execute(
        select(func.count(Review.id), func.avg(Review.aggregate_score))
    )
    review_row = reviews_q.one()
    total_reviews = int(review_row[0] or 0)
    avg_review = (
        Decimal(str(review_row[1])).quantize(Decimal("0.01"))
        if review_row[1] is not None
        else None
    )

    # Ledger totals
    platform_q = await session.execute(
        select(func.coalesce(func.sum(LedgerBalance.available), 0)).where(
            LedgerBalance.agent_did == PLATFORM_DID
        )
    )
    insurance_q = await session.execute(
        select(func.coalesce(func.sum(LedgerBalance.available), 0)).where(
            LedgerBalance.agent_did == INSURANCE_DID
        )
    )
    total_escrow_q = await session.execute(
        select(func.coalesce(func.sum(LedgerBalance.in_escrow), 0))
    )

    return {
        "agents": {"total_active": total_agents},
        "jobs": {
            "total": total_jobs,
            "completed": completed,
            "disputed": disputed,
            "by_status": by_status,
        },
        "reviews": {
            "total": total_reviews,
            "average": str(avg_review) if avg_review is not None else None,
        },
        "ledger": {
            "platform_revenue": str(platform_q.scalar() or Decimal("0")),
            "insurance_pool": str(insurance_q.scalar() or Decimal("0")),
            "total_in_escrow": str(total_escrow_q.scalar() or Decimal("0")),
            "currency": "EURC",
        },
    }
