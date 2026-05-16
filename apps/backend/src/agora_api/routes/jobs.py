"""Job lifecycle routes (Spec §6.4, §8.1, §9.2).

Off-chain ledger backs the escrow (ADR 003). State transitions are validated
in jobs_repo.transition(). Stage-1 dispute auto-resolution lives in
disputes_repo.code_as_judge().
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import agents_repo, disputes_repo, jobs_repo, ledger_repo, reviews_repo
from ..db.base import get_session
from ..db.jobs_repo import IllegalTransition
from ..db.ledger_repo import InsufficientFunds
from ..db.models import Agent, Job, JobStatus
from ..pricing import compute_fee

router = APIRouter()


class JobCreateRequest(BaseModel):
    requester_did: str
    provider_did: str
    task: dict[str, Any] = Field(default_factory=dict)
    budget: str = Field(..., description="Decimal EUR amount to lock in escrow")
    currency: str = "EURC"


class JobResultPayload(BaseModel):
    result: dict[str, Any]


class DisputePayload(BaseModel):
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


async def _load_agent_or_404(session: AsyncSession, did: str) -> Agent:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    return agent


async def _load_job_or_404(session: AsyncSession, job_id: str) -> Job:
    try:
        jid = uuid.UUID(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid job id: {e}") from e
    job = await jobs_repo.get(session, jid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job


async def _get_agent_by_id(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    return (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()


@router.post("", summary="Create a new job offer with escrow", status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        amount = Decimal(payload.budget)
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid budget: {e}") from e
    if amount <= 0:
        raise HTTPException(status_code=400, detail="budget must be > 0")

    requester = await _load_agent_or_404(session, payload.requester_did)
    provider = await _load_agent_or_404(session, payload.provider_did)
    if requester.did == provider.did:
        raise HTTPException(status_code=400, detail="requester and provider must differ")

    job = await jobs_repo.create(
        session,
        requester=requester,
        provider=provider,
        task_spec=payload.task,
        price_amount=amount,
        price_currency=payload.currency,
    )
    try:
        await ledger_repo.hold_escrow(session, requester.did, amount, job.id)
    except InsufficientFunds as e:
        await session.rollback()
        raise HTTPException(status_code=402, detail=str(e)) from e

    await session.commit()
    return jobs_repo.to_public_dict(job, requester.did, provider.did)


@router.get("/{job_id}", summary="Get job status")
async def get_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    r = await _get_agent_by_id(session, job.requester_agent_id)
    p = await _get_agent_by_id(session, job.provider_agent_id)
    return jobs_repo.to_public_dict(job, r.did, p.did)


@router.post("/{job_id}/accept", summary="Provider accepts the offer")
async def accept_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    try:
        await jobs_repo.transition(session, job, JobStatus.accepted)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await session.commit()
    return {"id": str(job.id), "status": job.status.value}


@router.post("/{job_id}/reject", summary="Provider rejects the offer; escrow refunded")
async def reject_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    if job.status != JobStatus.offered:
        raise HTTPException(
            status_code=409, detail=f"can only reject 'offered' jobs (was {job.status.value})"
        )
    r = await _get_agent_by_id(session, job.requester_agent_id)
    await ledger_repo.refund_escrow(session, r.did, job.price_amount, job.id)
    job.status = JobStatus.cancelled
    await session.flush()
    await session.commit()
    return {"id": str(job.id), "status": job.status.value}


@router.post("/{job_id}/result", summary="Provider submits result")
async def submit_result(
    job_id: str,
    payload: JobResultPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    try:
        await jobs_repo.transition(session, job, JobStatus.submitted)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    await jobs_repo.set_result(session, job, payload.result)
    await session.commit()
    return {"id": str(job.id), "status": job.status.value}


@router.post("/{job_id}/approve", summary="Requester approves; ledger releases escrow")
async def approve_job(
    job_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    if job.status != JobStatus.submitted:
        raise HTTPException(
            status_code=409,
            detail=f"can only approve 'submitted' jobs (was {job.status.value})",
        )

    breakdown = compute_fee(job.price_amount)
    r = await _get_agent_by_id(session, job.requester_agent_id)
    p = await _get_agent_by_id(session, job.provider_agent_id)

    await ledger_repo.release_escrow(
        session,
        payer_did=r.did,
        payee_did=p.did,
        amount=job.price_amount,
        platform_cut=breakdown.platform_cut,
        insurance_cut=breakdown.insurance_cut,
        payout=breakdown.payee_receives,
        job_id=job.id,
    )
    await jobs_repo.transition(session, job, JobStatus.completed)
    await reviews_repo.increment_jobs_completed(session, r)
    await reviews_repo.increment_jobs_completed(session, p)
    await session.commit()
    return {
        "id": str(job.id),
        "status": job.status.value,
        "fee": str(breakdown.fee),
        "payee_received": str(breakdown.payee_receives),
    }


@router.post("/{job_id}/dispute", summary="Open a dispute; runs Stage-1 code-as-judge")
async def open_dispute(
    job_id: str,
    payload: DisputePayload,
    raised_by_did: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    job = await _load_job_or_404(session, job_id)
    if job.status not in (JobStatus.accepted, JobStatus.in_progress, JobStatus.submitted):
        raise HTTPException(
            status_code=409, detail=f"cannot dispute from state {job.status.value}"
        )

    raiser_id = job.requester_agent_id
    if raised_by_did:
        raiser = await agents_repo.get_by_did(session, raised_by_did)
        if raiser is None:
            raise HTTPException(status_code=404, detail=f"agent {raised_by_did} not found")
        if raiser.id not in (job.requester_agent_id, job.provider_agent_id):
            raise HTTPException(status_code=403, detail="agent is not party to this job")
        raiser_id = raiser.id

    dispute = await disputes_repo.open_dispute(
        session,
        job=job,
        raised_by_id=raiser_id,
        reason=payload.reason,
        evidence=payload.evidence,
    )
    job.status = JobStatus.disputed
    await session.flush()

    verdict = disputes_repo.code_as_judge(job, payload.evidence)
    await disputes_repo.apply_verdict(session, dispute, verdict)

    r = await _get_agent_by_id(session, job.requester_agent_id)
    p = await _get_agent_by_id(session, job.provider_agent_id)
    if verdict.get("outcome") == "resolved":
        if verdict["winner"] == "requester":
            await ledger_repo.refund_escrow(session, r.did, job.price_amount, job.id)
            job.status = JobStatus.refunded
        elif verdict["winner"] == "provider":
            breakdown = compute_fee(job.price_amount)
            await ledger_repo.release_escrow(
                session,
                payer_did=r.did,
                payee_did=p.did,
                amount=job.price_amount,
                platform_cut=breakdown.platform_cut,
                insurance_cut=breakdown.insurance_cut,
                payout=breakdown.payee_receives,
                job_id=job.id,
            )
            job.status = JobStatus.completed
            await reviews_repo.increment_jobs_completed(session, r)
            await reviews_repo.increment_jobs_completed(session, p)
        await session.flush()

    await session.commit()
    return {
        "job_id": str(job.id),
        "job_status": job.status.value,
        "dispute": disputes_repo.to_public_dict(dispute),
    }


@router.get("", summary="List jobs (filter by requester_did, provider_did, status)")
async def list_jobs(
    requester_did: str | None = None,
    provider_did: str | None = None,
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if requester_did is None and provider_did is None:
        raise HTTPException(
            status_code=400, detail="must filter by requester_did or provider_did"
        )
    status_enum: JobStatus | None = None
    if status_filter is not None:
        try:
            status_enum = JobStatus(status_filter)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid status: {e}") from e

    if provider_did is not None:
        jobs = await jobs_repo.list_for_provider(session, provider_did, status=status_enum)
    else:
        assert requester_did is not None
        jobs = await jobs_repo.list_for_requester(session, requester_did, status=status_enum)

    out = []
    for job in jobs:
        r = await _get_agent_by_id(session, job.requester_agent_id)
        p = await _get_agent_by_id(session, job.provider_agent_id)
        out.append(jobs_repo.to_public_dict(job, r.did, p.did))
    return {"total": len(out), "jobs": out}


# ─── Dev: deposit funds + check balance ────────────────────


class DepositRequest(BaseModel):
    agent_did: str
    amount: str
    currency: str = "EURC"


@router.post(
    "/_admin/deposit",
    summary="(dev) Credit funds to an agent's ledger balance",
    status_code=status.HTTP_201_CREATED,
)
async def admin_deposit(
    payload: DepositRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        amount = Decimal(payload.amount)
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid amount: {e}") from e
    try:
        await ledger_repo.deposit(session, payload.agent_did, amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await session.commit()
    bal = await ledger_repo.get_balance(session, payload.agent_did, payload.currency)
    return {
        "agent_did": payload.agent_did,
        "available": str(bal.available),
        "in_escrow": str(bal.in_escrow),
    }


@router.get("/_admin/balance/{agent_did}", summary="(dev) Get an agent's ledger balance")
async def admin_balance(
    agent_did: str,
    currency: str = "EURC",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    bal = await ledger_repo.get_balance(session, agent_did, currency)
    return {
        "agent_did": agent_did,
        "currency": currency,
        "available": str(bal.available),
        "in_escrow": str(bal.in_escrow),
    }
