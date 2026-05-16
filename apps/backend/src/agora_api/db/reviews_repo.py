"""Review + reputation aggregation (Spec §6.6, ADR 008 Sprint 4)."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Job, Review, TrustLevel

# Five review dimensions (Spec §6.6). Each scored 1.0..5.0.
DIMENSIONS = ("accuracy", "speed", "cost", "reliability", "communication")


class InvalidScores(Exception):
    pass


def _validate_scores(scores: dict[str, Any]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for dim in DIMENSIONS:
        if dim not in scores:
            raise InvalidScores(f"missing dimension: {dim}")
        try:
            val = Decimal(str(scores[dim]))
        except Exception as e:
            raise InvalidScores(f"{dim} is not numeric: {e}") from e
        if val < Decimal("1") or val > Decimal("5"):
            raise InvalidScores(f"{dim} out of range 1..5: {val}")
        out[dim] = val
    return out


def _aggregate(scores: dict[str, Decimal]) -> Decimal:
    total = sum(scores.values(), Decimal("0"))
    avg = total / Decimal(len(DIMENSIONS))
    return avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def create_review(
    session: AsyncSession,
    *,
    job: Job,
    reviewer: Agent,
    reviewee: Agent,
    scores: dict[str, Any],
    comment: str | None = None,
    signature: str = "",
) -> Review:
    """Persist a review and refresh the reviewee's cached reputation."""
    validated = _validate_scores(scores)
    agg = _aggregate(validated)

    rev = Review(
        job_id=job.id,
        reviewer_agent_id=reviewer.id,
        reviewee_agent_id=reviewee.id,
        scores={k: str(v) for k, v in validated.items()},
        comment=comment,
        signature=signature,
        aggregate_score=agg,
    )
    session.add(rev)
    await session.flush()
    await refresh_reputation(session, reviewee)
    return rev


async def refresh_reputation(session: AsyncSession, agent: Agent) -> None:
    """Recompute and cache the agent's reputation_score and reputation_count."""
    result = await session.execute(
        select(
            func.count(Review.id),
            func.avg(Review.aggregate_score),
        ).where(Review.reviewee_agent_id == agent.id)
    )
    row = result.one()
    count = int(row[0] or 0)
    avg = row[1]
    agent.reputation_count = count
    agent.reputation_score = (
        Decimal(str(avg)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if avg is not None else None
    )
    # Auto trust-level promotion (ADR 007 / 008):
    # - 5 completed jobs + reputation >= 4.0 -> "verified" (if currently new/probation)
    # - 50 completed jobs + reputation >= 4.5 -> "trusted"
    if agent.reputation_score is not None:
        if (
            agent.jobs_completed >= 50
            and agent.reputation_score >= Decimal("4.5")
            and agent.trust_level != TrustLevel.banned
        ):
            agent.trust_level = TrustLevel.trusted
        elif (
            agent.jobs_completed >= 5
            and agent.reputation_score >= Decimal("4.0")
            and agent.trust_level in (TrustLevel.probation, TrustLevel.new)
        ):
            agent.trust_level = TrustLevel.verified
    await session.flush()


async def list_for_agent(
    session: AsyncSession, agent_did: str, *, limit: int = 50
) -> list[Review]:
    result = await session.execute(
        select(Review)
        .join(Agent, Agent.id == Review.reviewee_agent_id)
        .where(Agent.did == agent_did)
        .order_by(Review.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def has_reviewed(
    session: AsyncSession, *, reviewer_id: uuid.UUID, job_id: uuid.UUID
) -> bool:
    result = await session.execute(
        select(Review.id).where(
            Review.reviewer_agent_id == reviewer_id,
            Review.job_id == job_id,
        )
    )
    return result.first() is not None


def review_to_dict(review: Review) -> dict[str, Any]:
    return {
        "id": str(review.id),
        "job_id": str(review.job_id),
        "scores": review.scores or {},
        "aggregate": str(review.aggregate_score),
        "comment": review.comment,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


# ─── Increment jobs_completed counter (called by jobs_repo on completion) ──


async def increment_jobs_completed(session: AsyncSession, agent: Agent) -> None:
    agent.jobs_completed = (agent.jobs_completed or 0) + 1
    await session.flush()
