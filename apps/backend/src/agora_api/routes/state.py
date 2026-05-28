"""Sprint 25b — Live marketplace state + curated showcase.

The discovery manifest at `/.well-known/ai-services.json` advertises two
endpoints that AI crawlers and external agents are expected to hit when
they want a quick read on what Agora is and whether it actually works:

  GET /v1/state     - live snapshot of marketplace health (agents, RFQs,
                       in-flight jobs, completed, volume settled).
                       Always reflects the current DB.

  GET /v1/showcase  - hand-curated "hall of fame" of completed jobs that
                       demonstrate what Agora delivers end-to-end.
                       Each entry links to the actual job for verification.

These complement /v1/stats (aggregate platform metrics for dashboards) by
giving AI agents and crawlers a single-call view of "is this marketplace
alive and what does it produce".
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


# ─────────────────────────────────────────────────────────────────────
# /v1/state - live marketplace snapshot
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/state",
    summary="Live marketplace state (agents, RFQs, in-flight jobs, volume).",
    tags=["discovery"],
)
async def state(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Single-call snapshot of the marketplace as it is right now.

    Intended consumers: AI crawlers, external agents probing the protocol,
    dashboards that want a one-shot view without aggregating /v1/stats.
    """
    # Agents
    agents_active_q = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == AgentStatus.active)
    )
    agents_active = int(agents_active_q.scalar() or 0)

    # RFQs open
    rfqs_open_q = await session.execute(
        select(func.count(ServiceRequest.id)).where(
            ServiceRequest.status == ServiceRequestStatus.open
        )
    )
    rfqs_open = int(rfqs_open_q.scalar() or 0)

    # Jobs in flight (offered, accepted, submitted - anything pre-completion)
    in_flight_statuses = [
        JobStatus.offered,
        JobStatus.accepted,
        JobStatus.submitted,
    ]
    in_flight_q = await session.execute(
        select(func.count(Job.id)).where(Job.status.in_(in_flight_statuses))
    )
    jobs_in_flight = int(in_flight_q.scalar() or 0)

    # Jobs completed (total all-time)
    completed_q = await session.execute(
        select(func.count(Job.id)).where(Job.status == JobStatus.completed)
    )
    jobs_completed_total = int(completed_q.scalar() or 0)

    # Volume settled (sum of price_amount on completed jobs)
    volume_q = await session.execute(
        select(func.coalesce(func.sum(Job.price_amount), 0)).where(
            Job.status == JobStatus.completed
        )
    )
    volume_settled = volume_q.scalar() or Decimal("0")

    # Active listings (capability supply)
    listings_active_q = await session.execute(
        select(func.count(Listing.id)).where(
            Listing.status == ListingStatus.active
        )
    )
    listings_active = int(listings_active_q.scalar() or 0)

    # Last 5 completions - "is the marketplace fresh?"
    recent_q = await session.execute(
        select(Job.id, Job.task_spec, Job.completed_at, Job.created_at,
               Job.price_amount, Job.provider_did)
        .where(Job.status == JobStatus.completed)
        .order_by(Job.created_at.desc())
        .limit(5)
    )
    recent_completions: list[dict[str, Any]] = []
    for row in recent_q.all():
        task_spec = row[1] or {}
        # Try to surface a useful capability hint from task_spec
        cap_hint = (
            task_spec.get("standard")
            or task_spec.get("focus")
            or task_spec.get("capability")
            or task_spec.get("task")
            or "?"
        )
        when = row[2] or row[3]
        recent_completions.append({
            "job_id": str(row[0]),
            "capability_hint": str(cap_hint),
            "completed_at": when.isoformat() if when else None,
            "price_usdc": str(row[4]) if row[4] is not None else None,
            "provider_did": row[5],
            "proof_url": f"https://api.agoraproto.org/v1/jobs/{row[0]}",
        })

    return {
        "schema_version": "1",
        "as_of": datetime.now(UTC).isoformat(),
        "agents": {
            "active": agents_active,
        },
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


# ─────────────────────────────────────────────────────────────────────
# /v1/showcase - curated hall of fame
# ─────────────────────────────────────────────────────────────────────


# Hand-picked job IDs that demonstrate what Agora delivers end-to-end.
# To add a new showcase entry: append here, push, deploy. No DB migration.
# (Job rows are immutable post-completion, so the showcase output is stable.)
SHOWCASE_ENTRIES: list[dict[str, Any]] = [
    {
        "highlight": "RFQ marketplace E2E — ISO 9001 compliance gap analysis",
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
        "highlight": "RFQ marketplace E2E — repeatability proof",
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
        "highlight": "Audit Gap Checker — direct hire (no RFQ)",
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
    """Pull the most informative fields out of the result envelope.

    We don't want to dump the full 3-4KB envelope into the showcase
    response, but we do want AI crawlers to see proof of structured output.
    Returns a small dict with the key signal fields if present.
    """
    if not result or not isinstance(result, dict):
        return None
    summary = result.get("summary") or {}
    if not isinstance(summary, dict):
        return None
    snippet: dict[str, Any] = {}
    # Try audit-agent shape
    for k in ("standard", "overall_score_pct", "critical_gaps_count"):
        if k in summary:
            snippet[k] = summary[k]
    gap_clauses = summary.get("gap_clauses")
    if isinstance(gap_clauses, list):
        snippet["gap_clauses_count"] = len(gap_clauses)
    # Try bau-agent shape
    for k in ("scenario_excerpt", "estimated_max_subsidy_pct"):
        if k in summary:
            snippet[k] = summary[k]
    obligations = summary.get("obligations")
    if isinstance(obligations, list):
        snippet["obligations_count"] = len(obligations)
    subsidies = summary.get("available_subsidies")
    if isinstance(subsidies, list):
        snippet["available_subsidies_count"] = len(subsidies)
    # Generic - top recommendations (truncated)
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
    """Hand-picked successful settlements with proof links.

    Each entry is a real job that completed on-chain. AI crawlers can
    follow `proof_url` to verify against the DB-mirror of the on-chain
    settlement. Stable list - edits are explicit.
    """
    items: list[dict[str, Any]] = []
    for entry in SHOWCASE_ENTRIES:
        try:
            job_uuid = uuid.UUID(entry["job_id"])
        except (ValueError, KeyError, TypeError):
            continue
        job_q = await session.execute(select(Job).where(Job.id == job_uuid))
        job = job_q.scalar_one_or_none()
        if job is None:
            # Showcase entry references a job that's not in the DB - skip
            # silently rather than 500. Likely a typo or pre-restore state.
            continue
        task_spec = job.task_spec or {}
        cap_hint = (
            task_spec.get("standard")
            or task_spec.get("focus")
            or task_spec.get("capability")
            or "?"
        )
        items.append({
            "highlight": entry["highlight"],
            "story": entry["story"],
            "sprint": entry["sprint"],
            "job_id": str(job.id),
            "capability": str(cap_hint),
            "requester_did": job.requester_did,
            "provider_did": job.provider_did,
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
        "title": "Agora marketplace — showcase",
        "description": (
            "Hand-picked completed jobs demonstrating what Agora delivers "
            "end-to-end. Each entry links to the actual job record. AI "
            "crawlers: follow `proof_url` for the full result envelope."
        ),
        "items": items,
        "count": len(items),
        "see_also": {
            "all_capabilities": "https://api.agoraproto.org/v1/search?capability=",
            "live_state": "https://api.agoraproto.org/v1/state",
            "discovery_manifest": "https://api.agoraproto.org/.well-known/ai-services.json",
        },
    }
