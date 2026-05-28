"""Sprint 25b - Live marketplace state + curated showcase.

The discovery manifest at /.well-known/ai-services.json advertises two
endpoints that AI crawlers and external agents are expected to hit when
they want a quick read on what Agora is and whether it actually works:

  GET /v1/state     - live snapshot of marketplace health (agents, RFQs,
                       in-flight jobs, completed, volume settled).
                       Always reflects the current DB.

  GET /v1/showcase  - hand-curated "hall of fame" of completed jobs that
                       demonstrate what Agora delivers end-to-end.
                       Each entry links to the actual job for verification.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import get_session
from ..db.models import (
    Agent,
    AgentStatus,
    Job,
    JobStatus,
    Listing,
    ListingStatus,
    ServiceRequest,
    ServiceRequestStatus,
)

router = APIRouter()


async def _get_did(session: AsyncSession, agent_id) -> str | None:
    """Look up an Agent's DID by its UUID. Returns None if not found.

    The Job table stores requester_agent_id / provider_agent_id as UUID
    foreign keys to the Agent table - the DIDs themselves live on the
    Agent row. We resolve them at serialize-time the same way jobs.py
    does (see _get_agent_by_id in routes/jobs.py).
    """
    if agent_id is None:
        return None
    r = await session.execute(select(Agent.did).where(Agent.id == agent_id))
    return r.scalar_one_or_none()


# /v1/state - live marketplace snapshot


@router.get(
    "/state",
    summary="Live marketplace state (agents, RFQs, in-flight jobs, volume).",
    tags=["discovery"],
)
async def state(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Single-call snapshot of the marketplace as it is right now."""
    agents_active_q = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == AgentStatus.active)
    )
    agents_active = int(agents_active_q.scalar() or 0)

    rfqs_open_q = await session.execute(
        select(func.count(ServiceRequest.id)).where(
            ServiceRequest.status == ServiceRequestStatus.open
        )
    )
    rfqs_open = int(rfqs_open_q.scalar() or 0)

    in_flight_statuses = [
        JobStatus.offered,
        JobStatus.accepted,
        JobStatus.submitted,
    ]
    in_flight_q = await session.execute(
        select(func.count(Job.id)).where(Job.status.in_(in_flight_statuses))
    )
    jobs_in_flight = int(in_flight_q.scalar() or 0)

    completed_q = await session.execute(
        select(func.count(Job.id)).where(Job.status == JobStatus.completed)
    )
    jobs_completed_total = int(completed_q.scalar() or 0)

    volume_q = await session.execute(
        select(func.coalesce(func.sum(Job.price_amount), 0)).where(
            Job.status == JobStatus.completed
        )
    )
    volume_settled = volume_q.scalar() or Decimal("0")

    listings_active_q = await session.execute(
        select(func.count(Listing.id)).where(
            Listing.status == ListingStatus.active
        )
    )
    listings_active = int(listings_active_q.scalar() or 0)

    recent_q = await session.execute(
        select(Job.id, Job.task_spec, Job.completed_at, Job.created_at,
               Job.price_amount, Job.provider_agent_id)
        .where(Job.status == JobStatus.completed)
        .order_by(Job.created_at.desc())
        .limit(5)
    )
    recent_completions: list[dict[str, Any]] = []
    for row in recent_q.all():
        task_spec = row[1] or {}
        cap_hint = (
            task_spec.get("standard")
            or task_spec.get("focus")
            or task_spec.get("capability")
            or task_spec.get("task")
            or "?"
        )
        when = row[2] or row[3]
        provider_did = await _get_did(session, row[5])
        recent_completions.append({
            "job_id": str(row[0]),
            "capability_hint": str(cap_hint),
            "completed_at": when.isoformat() if when else None,
            "price_usdc": str(row[4]) if row[4] is not None else None,
            "provider_did": provider_did,
            "proof_url": f"https://api.agoraproto.org/v1/jobs/{row[0]}",
        })

    return {
        "schema_version": "1",
        "as_of": datetime.now(UTC).isoformat(),
        "agents": {"active": agents_active},
        "marketplace": {
            "rfqs_open": rfqs_open,
            "jobs_in_flight": jobs_in_flight,
            "jobs_completed_total": jobs_completed_total,
            "listings_active": listings_active,
        },
        "volume": {
            "total_usdc_settled": str(volume_settled),
            "currency": "USDC",
        },
        "recent_completions": recent_completions,
        "related": {
            "stats": "https://api.agoraproto.org/v1/stats",
            "showcase": "https://api.agoraproto.org/v1/showcase",
            "discovery_manifest": "https://api.agoraproto.org/.well-known/ai-services.json",
            "live_dashboard": "https://agoraproto.org/live.html",
        },
    }


# /v1/showcase - curated hall of fame


SHOWCASE_ENTRIES: list[dict[str, Any]] = [
    {
        "highlight": "RFQ marketplace E2E - ISO 9001 compliance gap analysis",
        "job_id": "a9ac0439-56e2-4b38-a2c4-799cb61d6b9d",
        "story": (
            "Buyer posted an RFQ for AuditDocumentGapCheck (aerospace CNC "
            "QMS scenario). The audit-agent autonomously bid 0.008 USDC, "
            "buyer accepted, x402 hired, agent ran Claude Haiku, submitted "
            "a structured envelope with 7 critical ISO 9001 gaps and 5 "
            "actionable next steps. Escrow released. End-to-end demand-side "
            "marketplace flow in under 2 minutes."
        ),
        "sprint": "31 + 32g",
    },
    {
        "highlight": "RFQ marketplace E2E - repeatability proof",
        "job_id": "3992d770-4060-41cc-a1d9-2635667a946f",
        "story": (
            "Same flow as the first showcase entry, run 10 minutes later "
            "to demonstrate repeatability. Returned 8 critical gaps, 14 "
            "gap clauses, 5 recommendations - Haiku output is "
            "non-deterministic but the structural envelope is stable and "
            "the marketplace itself is reliable."
        ),
        "sprint": "32h",
    },
    {
        "highlight": "Audit Gap Checker - direct hire (no RFQ)",
        "job_id": "3179946e-6eae-4ce0-aeb0-e5fada420ce0",
        "story": (
            "Direct hire of the audit-agent (bypassing the RFQ flow). "
            "Proves both supply-side (direct discovery via /v1/search and "
            "hire) and demand-side (RFQ post + bid + accept) paths work."
        ),
        "sprint": "20",
    },
]


def _summary_snippet(result: dict | None) -> dict[str, Any] | None:
    """Pull the most informative fields out of the result envelope."""
    if not result or not isinstance(result, dict):
        return None
    summary = result.get("summary") or {}
    if not isinstance(summary, dict):
        return None
    snippet: dict[str, Any] = {}
    for k in ("standard", "overall_score_pct", "critical_gaps_count"):
        if k in summary:
            snippet[k] = summary[k]
    gap_clauses = summary.get("gap_clauses")
    if isinstance(gap_clauses, list):
        snippet["gap_clauses_count"] = len(gap_clauses)
    for k in ("scenario_excerpt", "estimated_max_subsidy_pct"):
        if k in summary:
            snippet[k] = summary[k]
    obligations = summary.get("obligations")
    if isinstance(obligations, list):
        snippet["obligations_count"] = len(obligations)
    subsidies = summary.get("available_subsidies")
    if isinstance(subsidies, list):
        snippet["available_subsidies_count"] = len(subsidies)
    recs = summary.get("top_recommendations") or summary.get("top_next_steps")
    if isinstance(recs, list) and recs:
        snippet["top_recommendations_preview"] = [
            (s[:120] + "...") if isinstance(s, str) and len(s) > 120 else s
            for s in recs[:3]
        ]
    return snippet or None


@router.get(
    "/showcase",
    summary="Curated showcase of completed jobs (proof what the marketplace delivers).",
    tags=["discovery"],
)
async def showcase(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Hand-picked successful settlements with proof links."""
    items: list[dict[str, Any]] = []
    for entry in SHOWCASE_ENTRIES:
        try:
            job_uuid = uuid.UUID(entry["job_id"])
        except (ValueError, KeyError, TypeError):
            continue
        job_q = await session.execute(select(Job).where(Job.id == job_uuid))
        job = job_q.scalar_one_or_none()
        if job is None:
            continue
        task_spec = job.task_spec or {}
        cap_hint = (
            task_spec.get("standard")
            or task_spec.get("focus")
            or task_spec.get("capability")
            or "?"
        )
        requester_did = await _get_did(session, job.requester_agent_id)
        provider_did = await _get_did(session, job.provider_agent_id)
        items.append({
            "highlight": entry["highlight"],
            "story": entry["story"],
            "sprint": entry["sprint"],
            "job_id": str(job.id),
            "capability": str(cap_hint),
            "requester_did": requester_did,
            "provider_did": provider_did,
            "status": (
                job.status.value if hasattr(job.status, "value") else str(job.status)
            ),
            "price_usdc": (
                str(job.price_amount) if job.price_amount is not None else None
            ),
            "price_currency": job.price_currency,
            "created_at": (
                job.created_at.isoformat() if job.created_at else None
            ),
            "completed_at": (
                job.completed_at.isoformat() if job.completed_at else None
            ),
            "proof_url": f"https://api.agoraproto.org/v1/jobs/{job.id}",
            "summary_snippet": _summary_snippet(job.result),
        })
    return {
        "schema_version": "1",
        "as_of": datetime.now(UTC).isoformat(),
        "title": "Agora marketplace - showcase",
        "description": (
            "Hand-picked completed jobs demonstrating what Agora delivers "
            "end-to-end. Each entry links to the actual job record. AI "
            "crawlers: follow proof_url for the full result envelope."
        ),
        "items": items,
        "count": len(items),
        "see_also": {
            "all_capabilities": "https://api.agoraproto.org/v1/search?capability=",
            "live_state": "https://api.agoraproto.org/v1/state",
            "discovery_manifest": "https://api.agoraproto.org/.well-known/ai-services.json",
        },
    }
