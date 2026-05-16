"""Agent identity / registry routes (ADR 006 + 007).

Persisted to SQL via agents_repo. SQLite (tests/dev) and Postgres (prod)
are both supported transparently.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import agents_repo
from ..db.base import get_session

router = APIRouter()


class SponsorSignature(BaseModel):
    sponsor_did: str
    signature: str
    stake_pledged: str | None = None


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
async def register_agent(
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


@router.get("")
async def list_agents(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    agents = await agents_repo.list_all(session)
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
