"""Chain watcher — reconcile on-chain job status with the DB.

The x402 endpoints already mutate the DB *during* the on-chain request
because the agent signs the tx and immediately reports the hash back to
the API. But agents are free to talk to `AgoraEscrow` directly (the
contract is permissionless) — they might call `submitResult` or
`approveAndPay` from a different client, never tell our API, and the DB
would drift.

This worker fixes that. Once per `chain_watcher_interval_seconds` it:

1. Selects every on-chain job whose DB status is non-terminal
   (`offered`, `submitted`, `disputed`).
2. Reads the corresponding `jobs(jobId)` from the contract.
3. Compares the on-chain enum to the DB enum. If they differ, updates
   the DB to match the chain and fires the appropriate webhook so the
   agent who *was* paying attention to webhooks still gets notified.

This is one-way reconciliation: chain is authoritative. The watcher
never writes to chain.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import agents_repo
from ..db.base import get_sessionmaker
from ..db.models import Job, JobStatus
from ..webhooks.delivery import enqueue_for_agent
from . import get_escrow_client

log = logging.getLogger(__name__)


# AgoraEscrow.JobStatus enum:
#   V1: 0 None, 1 Funded, 2 Submitted, 3 Approved, 4 Disputed, 5 Refunded
#   V2: same + 6 Resolved (owner-arbitrated dispute split, terminal state)
#
# Sprint 35a: V2's Resolved (6) is functionally a completion - the funds
# flowed, the job is closed, the split was owner-decided. The marketplace
# does not differentiate between Approved-style and Resolved-style
# completions at the JobStatus level; the JobResolved event in the log
# carries the actual split numbers (payeeAmount, payerAmount, fee,
# insuranceCut) for off-chain accounting.
_CHAIN_TO_DB: dict[int, JobStatus] = {
    1: JobStatus.offered,
    2: JobStatus.submitted,
    3: JobStatus.completed,
    4: JobStatus.disputed,
    5: JobStatus.refunded,
    6: JobStatus.completed,  # V2 Resolved -> completed
}

_EVENT_NAMES: dict[JobStatus, str] = {
    JobStatus.submitted: "job.result_submitted",
    JobStatus.completed: "job.completed",
    JobStatus.disputed: "job.disputed",
    JobStatus.refunded: "job.refunded",
}

# DB statuses we still actively monitor (terminal states are skipped).
_LIVE_DB_STATUSES = (JobStatus.offered, JobStatus.submitted, JobStatus.disputed)


async def chain_watcher_loop(stop_event: asyncio.Event) -> None:
    """Background task; lifecycle-managed by FastAPI's lifespan.

    Exits when `stop_event` fires. Never raises — every internal error
    is logged and the loop continues. The watcher is a *helper*, not a
    source of truth, so it must not be able to take the API process down.
    """
    settings = get_settings()
    interval = max(5.0, float(settings.chain_watcher_interval_seconds))

    client = get_escrow_client()
    if client is None:
        log.info("chain_watcher.idle: on-chain payments disabled or unconfigured")
        await stop_event.wait()
        return

    log.info("chain_watcher.start interval=%.1fs", interval)
    while not stop_event.is_set():
        try:
            await _sweep_once(client)
        except Exception:
            log.exception("chain_watcher.sweep_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass  # normal tick — just continue
    log.info("chain_watcher.stop")


async def _sweep_once(client: Any) -> None:
    """One pass: find all live on-chain jobs and reconcile each."""
    sm = get_sessionmaker()
    # Sprint 36g: only reconcile jobs whose recorded escrow address matches
    # the current settings.escrow_contract_address. Legacy jobs (NULL
    # column, created before Sprint 36g) and jobs from a previous contract
    # version are skipped here rather than producing unknown_status log
    # spam against a contract that doesn't know their job_ids.
    from ..config import get_settings
    current_escrow = get_settings().escrow_contract_address
    async with sm() as session:
        result = await session.execute(
            select(Job).where(
                Job.settlement_mode == "onchain",
                Job.status.in_(_LIVE_DB_STATUSES),
                Job.onchain_job_id.is_not(None),
                Job.escrow_contract_address == current_escrow,
            )
        )
        jobs = list(result.scalars().all())
        if not jobs:
            return
        log.debug("chain_watcher.sweep n=%d", len(jobs))
        any_change = False
        for job in jobs:
            try:
                changed = await _reconcile_one(session, client, job)
                any_change = any_change or changed
            except Exception:
                log.exception(
                    "chain_watcher.reconcile_failed job_id=%s onchain_job_id=%s",
                    job.id,
                    job.onchain_job_id,
                )
        if any_change:
            await session.commit()


async def _reconcile_one(
    session: AsyncSession,
    client: Any,
    job: Job,
) -> bool:
    """Reconcile a single job. Returns True iff DB state changed."""
    onchain = await client.get_job(int(job.onchain_job_id))
    target = _CHAIN_TO_DB.get(int(onchain.status))
    if target is None:
        # Status 0 (None) shouldn't happen for known job ids — log and skip.
        log.warning(
            "chain_watcher.unknown_status onchain_job_id=%s raw=%s",
            job.onchain_job_id,
            onchain.status,
        )
        return False
    if target == job.status:
        return False

    log.info(
        "chain_watcher.drift_detected job_id=%s onchain_job_id=%s db=%s chain=%s",
        job.id,
        job.onchain_job_id,
        job.status.value,
        target.value,
    )
    job.status = target
    await session.flush()

    # Tell whichever agent is waiting for this state change.
    requester = await agents_repo.get_by_id(session, job.requester_agent_id)
    provider = await agents_repo.get_by_id(session, job.provider_agent_id)
    event_name = _EVENT_NAMES.get(target, "job.chain_observed")
    payload = {
        "job_id": str(job.id),
        "onchain_job_id": job.onchain_job_id,
        "status": target.value,
    }
    if event_name != "job.chain_observed":
        if requester is not None:
            await enqueue_for_agent(
                session,
                agent=requester,
                job_id=job.id,
                event_type=event_name,
                payload=payload,
            )
        if provider is not None:
            await enqueue_for_agent(
                session,
                agent=provider,
                job_id=job.id,
                event_type=event_name,
                payload=payload,
            )
    return True
