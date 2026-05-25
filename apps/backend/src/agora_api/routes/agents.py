"""Agent identity / registry routes (ADR 006 + 007).

Persisted to SQL via agents_repo. SQLite (tests/dev) and Postgres (prod)
are both supported transparently.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import agents_repo
from ..db.base import get_session
from ..rate_limit import limiter
from ..sponsor import SponsorshipInvalid, check_eligibility, verify_signature

router = APIRouter()


class SponsorSignature(BaseModel):
    sponsor_did: str
    signature: str = Field(
        ...,
        description=(
            "Base64-encoded Ed25519 signature over the canonical sponsor payload "
            "(see docs/sponsor.md). The sponsor's signing key is recovered from "
            "the publicKeyMultibase in their DID document."
        ),
    )
    stake_pledged: str = Field(
        default="5.00",
        description="Amount in EUR the sponsor risks if the new agent gets banned within 90 days.",
    )
    valid_until_unix: int = Field(
        ...,
        description="Unix timestamp after which this sponsorship is invalid (ADR 007).",
    )


class CapabilityDecl(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class AgentRegisterRequest(BaseModel):
    did_document: dict[str, Any]
    name: str
    description: str = ""
    owner_did: str
    capabilities: list[CapabilityDecl]
    pricing: dict[str, Any]
    endpoint_url: str = ""
    stake_eur: str = "5.00"
    sponsor: SponsorSignature | None = None


class AgentRegisterResponse(BaseModel):
    did: str
    trust_level: str
    webhook_secret: str
    registered_at: str
    notes: list[str] = Field(default_factory=list)


@router.post(
    "/register",
    response_model=AgentRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(lambda: get_settings().rate_limit_register)
async def register_agent(
    request: Request,
    payload: AgentRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentRegisterResponse:
    did = payload.did_document.get("id")
    if not isinstance(did, str) or not did.startswith("did:agora:"):
        raise HTTPException(
            status_code=400,
            detail="did_document.id must be a did:agora: identifier",
        )

    existing = await agents_repo.get_by_did(session, did)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"agent {did} already registered")

    try:
        stake = Decimal(payload.stake_eur)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid stake: {e}") from e

    if stake < Decimal("5") and payload.sponsor is None:
        raise HTTPException(
            status_code=400,
            detail="minimum stake is 5 EUR (or provide a sponsor signature, ADR 007)",
        )

    # ── Verify sponsor signature (ADR 007 Anti-Sybil) ────────────────
    if payload.sponsor is not None:
        sponsor_agent = await agents_repo.get_by_did(session, payload.sponsor.sponsor_did)
        if sponsor_agent is None:
            raise HTTPException(
                status_code=400,
                detail=f"sponsor {payload.sponsor.sponsor_did} not found on Agora",
            )
        try:
            check_eligibility(sponsor_agent)
            verify_signature(
                sponsor=sponsor_agent,
                new_agent_did=did,
                stake_pledged=payload.sponsor.stake_pledged,
                valid_until_unix=payload.sponsor.valid_until_unix,
                signature_b64=payload.sponsor.signature,
            )
        except SponsorshipInvalid as e:
            raise HTTPException(status_code=400, detail=f"sponsorship rejected: {e}") from e

    try:
        agent, webhook_secret = await agents_repo.create(
            session,
            did=did,
            did_document=payload.did_document,
            name=payload.name,
            description=payload.description,
            owner_did=payload.owner_did,
            capabilities=[c.model_dump() for c in payload.capabilities],
            pricing=payload.pricing,
            endpoint_url=payload.endpoint_url,
            stake_eur=stake,
            sponsor_did=payload.sponsor.sponsor_did if payload.sponsor else None,
            sponsor_signature=payload.sponsor.signature if payload.sponsor else None,
        )
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"agent conflict: {e.orig}") from e

    notes: list[str] = []
    if agent.trust_level.value == "probation":
        notes.append(
            "Probation: hidden from search until trust improves. "
            "Increase stake or add sponsor (ADR 007)."
        )
    elif agent.trust_level.value == "new":
        notes.append("New: visible in search with 'new' badge. Max 5 EUR/job for first 30 days.")

    return AgentRegisterResponse(
        did=agent.did,
        trust_level=agent.trust_level.value,
        webhook_secret=webhook_secret,
        registered_at=agent.created_at.isoformat(),
        notes=notes,
    )


@router.get("/{did}")
async def get_agent(
    did: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    return agents_repo.to_public_dict(agent)


# ─────────────────────────────────────────────────────────────────────
# Test-data heuristic (Sprint 27a — external audit finding #5).
# Sprint-19 verification agents and bootstrap-funding probes are
# development artefacts that pollute the public registry. Filter them
# out of the default listing; callers who deliberately want to see
# them (debug dashboards, the audit dashboard itself) can pass
# ?include_test=true.
# ─────────────────────────────────────────────────────────────────────


def _is_test_agent(agent: Any) -> bool:
    """Heuristic: name or capability tags this as a development artefact.

    Match conditions (any one is enough):
      - Name starts with 'Sprint <n>' (e.g. 'Sprint 19 Verify')
      - Name starts with 'Test '
      - Any capability type contains 'sprint', 'debug', 'test',
        'bootstrapautofund'
    """
    import re

    name = (getattr(agent, "name", "") or "").strip()
    name_lower = name.lower()

    if re.match(r"^sprint\s+\d", name_lower):
        return True
    if name_lower.startswith("test "):
        return True

    caps = getattr(agent, "capabilities", []) or []
    bad_substrings = ("sprint", "debug", "test", "bootstrapautofund")
    for c in caps:
        ctype = (c.get("type", "") if isinstance(c, dict) else "").lower()
        if any(s in ctype for s in bad_substrings):
            return True

    return False


@router.get("")
async def list_agents(
    session: AsyncSession = Depends(get_session),
    include_test: bool = False,
) -> dict[str, Any]:
    """List active agents.

    By default development/test agents (Sprint X Verify, BootstrapAutoFund,
    *Debug capabilities) are hidden so the public registry stays clean.
    Pass `?include_test=true` to include them — useful for the admin
    dashboard or for debugging.
    """
    agents = await agents_repo.list_all(session)
    if not include_test:
        agents = [a for a in agents if not _is_test_agent(a)]
    return {
        "total": len(agents),
        "agents": [agents_repo.to_public_dict(a) for a in agents],
    }


@router.delete("/{did}")
async def deactivate_agent(
    did: str, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    await agents_repo.archive(session, agent)
    await session.commit()
    return {"did": did, "status": "archived"}
