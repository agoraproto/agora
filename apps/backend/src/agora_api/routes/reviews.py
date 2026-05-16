"""Review + reputation routes (Spec §6.6)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import agents_repo, jobs_repo, reviews_repo
from ..db.base import get_session
from ..db.models import Agent, JobStatus
from ..db.reviews_repo import DIMENSIONS, InvalidScores

router = APIRouter()


class ReviewSubmission(BaseModel):
    job_id: str
    reviewer_did: str
    scores: dict[str, Any] = Field(
        ..., description="5-dim scores: accuracy, speed, cost, reliability, communication (1..5)"
    )
    comment: str | None = None
    signature: str = ""


@router.post(
    "/reviews",
    summary="Submit a review for a completed job",
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    payload: ReviewSubmission,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        job_uuid = uuid.UUID(payload.job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid job id: {e}") from e

    job = await jobs_repo.get(session, job_uuid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {payload.job_id} not found")
    if job.status != JobStatus.completed:
        raise HTTPException(
            status_code=409,
            detail=f"can only review completed jobs (was {job.status.value})",
        )

    reviewer = await agents_repo.get_by_did(session, payload.reviewer_did)
    if reviewer is None:
        raise HTTPException(status_code=404, detail=f"reviewer {payload.reviewer_did} not found")
    if reviewer.id not in (job.requester_agent_id, job.provider_agent_id):
        raise HTTPException(
            status_code=403, detail="reviewer was not a party to this job"
        )

    if await reviews_repo.has_reviewed(session, reviewer_id=reviewer.id, job_id=job.id):
        raise HTTPException(status_code=409, detail="reviewer already submitted a review for this job")

    # Reviewee is the other party
    reviewee_id = (
        job.provider_agent_id if reviewer.id == job.requester_agent_id else job.requester_agent_id
    )
    reviewee = (
        await session.execute(select(Agent).where(Agent.id == reviewee_id))
    ).scalar_one()

    try:
        review = await reviews_repo.create_review(
            session,
            job=job,
            reviewer=reviewer,
            reviewee=reviewee,
            scores=payload.scores,
            comment=payload.comment,
            signature=payload.signature,
        )
    except InvalidScores as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    await session.commit()
    return {
        "id": str(review.id),
        "aggregate": str(review.aggregate_score),
        "reviewee_did": reviewee.did,
        "reviewee_reputation": str(reviewee.reputation_score) if reviewee.reputation_score else None,
        "reviewee_reputation_count": reviewee.reputation_count,
        "reviewee_trust_level": reviewee.trust_level.value,
    }


@router.get("/agents/{did}/reviews", summary="List reviews for an agent")
async def list_reviews_for_agent(
    did: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    reviews = await reviews_repo.list_for_agent(session, did, limit=limit)
    return {
        "total": len(reviews),
        "reviews": [reviews_repo.review_to_dict(r) for r in reviews],
    }


@router.get("/agents/{did}/reputation", summary="Aggregated reputation for an agent")
async def get_reputation(
    did: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    return {
        "did": agent.did,
        "score": str(agent.reputation_score) if agent.reputation_score is not None else None,
        "count": agent.reputation_count,
        "trust_level": agent.trust_level.value,
        "jobs_completed": agent.jobs_completed,
        "dimensions": list(DIMENSIONS),
    }
