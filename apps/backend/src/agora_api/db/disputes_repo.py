"""Dispute persistence + Stage-1 code-as-judge resolution (Spec §6.7)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Dispute, DisputeStatus, Job


async def get_for_job(session: AsyncSession, job_id: uuid.UUID) -> Dispute | None:
    result = await session.execute(select(Dispute).where(Dispute.job_id == job_id))
    return result.scalar_one_or_none()


async def open_dispute(
    session: AsyncSession,
    *,
    job: Job,
    raised_by_id: uuid.UUID,
    reason: str,
    evidence: dict[str, Any],
) -> Dispute:
    dispute = Dispute(
        job_id=job.id,
        raised_by_agent_id=raised_by_id,
        reason=reason,
        evidence=evidence,
        status=DisputeStatus.open,
    )
    session.add(dispute)
    await session.flush()
    return dispute


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def code_as_judge(job: Job, dispute_evidence: dict[str, Any]) -> dict[str, Any]:
    """Stage-1 automated arbitration (ADR 008 / Spec §6.7).

    A pure-function judge that decides simple, deterministic cases.
    Stage-2 (verifier consensus) and Stage-3 (human) are out of scope.

    Heuristics for MVP:
      1. If the task declared an `expected` field and result matches -> for provider.
      2. If the task type is "Echo" and result.echoed == task.prompt -> for provider.
      3. If the task declared `expected_hash` and result hashes match -> for provider.
      4. Otherwise -> escalate (Stage-2 / human).
    """
    task = job.task_spec or {}
    result = job.result or {}

    if "expected" in task:
        if result.get("result") == task["expected"]:
            return _verdict("provider", "result matched expected")
        return _verdict("requester", f"result did not match expected ({task['expected']!r})")

    if task.get("type") == "Echo" or any(
        c == "Echo" for c in (task.get("capabilities") or [])
    ):
        prompt = task.get("prompt") or task.get("input")
        echoed = result.get("echoed") or (result.get("result") or {}).get("echoed")
        if echoed is not None and prompt is not None:
            if str(echoed).strip() == str(prompt).strip():
                return _verdict("provider", "echo matches prompt")
            return _verdict("requester", "echo does not match prompt")

    if "expected_hash" in task:
        if _stable_hash(result) == task["expected_hash"]:
            return _verdict("provider", "result hash matches expected_hash")
        return _verdict("requester", "result hash differs from expected_hash")

    # No deterministic check available - escalate.
    return {
        "outcome": "escalate",
        "reason": "no deterministic verification possible at Stage 1",
        "evidence_summary": list(dispute_evidence.keys()),
    }


def _verdict(winner: str, reason: str) -> dict[str, Any]:
    return {"outcome": "resolved", "winner": winner, "reason": reason}


async def apply_verdict(session: AsyncSession, dispute: Dispute, verdict: dict[str, Any]) -> None:
    dispute.resolution = verdict
    dispute.resolved_by = "stage-1-code-as-judge"
    if verdict.get("outcome") == "resolved":
        if verdict["winner"] == "provider":
            dispute.status = DisputeStatus.resolved_for_provider
        else:
            dispute.status = DisputeStatus.resolved_for_requester
    else:
        dispute.status = DisputeStatus.escalated
    await session.flush()


def to_public_dict(dispute: Dispute) -> dict[str, Any]:
    return {
        "id": str(dispute.id),
        "job_id": str(dispute.job_id),
        "reason": dispute.reason,
        "status": dispute.status.value,
        "resolution": dispute.resolution,
        "resolved_by": dispute.resolved_by,
        "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
        "created_at": dispute.created_at.isoformat() if dispute.created_at else None,
    }
