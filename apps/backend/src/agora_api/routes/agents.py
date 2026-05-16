"""Agent identity / registry routes (ADR 006 + 007). In-memory MVP."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

router = APIRouter()

_AGENTS: dict[str, dict[str, Any]] = {}


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


def _trust_level_from(stake: Decimal, sponsor: SponsorSignature | None) -> str:
    if sponsor is not None:
        return "new"
    if stake >= Decimal("100"):
        return "verified"
    if stake >= Decimal("25"):
        return "new"
    return "probation"


@router.post("/register", response_model=AgentRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(payload: AgentRegisterRequest) -> AgentRegisterResponse:
    did = payload.did_document.get("id")
    if not isinstance(did, str) or not did.startswith("did:agora:"):
        raise HTTPException(status_code=400, detail="did_document.id must be a did:agora: identifier")
    if did in _AGENTS:
        raise HTTPException(status_code=409, detail=f"agent {did} already registered")
    try:
        stake = Decimal(payload.stake_eur)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid stake: {e}") from e
    if stake < Decimal("5") and payload.sponsor is None:
        raise HTTPException(status_code=400, detail="minimum stake is 5 EUR (or provide a sponsor signature, ADR 007)")

    trust = _trust_level_from(stake, payload.sponsor)
    webhook_secret = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()

    _AGENTS[did] = {
        "did": did,
        "name": payload.name,
        "description": payload.description,
        "owner_did": payload.owner_did,
        "capabilities": [c.model_dump() for c in payload.capabilities],
        "pricing": payload.pricing,
        "endpoint_url": payload.endpoint_url,
        "stake_eur": str(stake),
        "sponsor": payload.sponsor.model_dump() if payload.sponsor else None,
        "trust_level": trust,
        "webhook_secret": webhook_secret,
        "registered_at": now,
    }

    notes = []
    if trust == "probation":
        notes.append("Probation: hidden from search until trust improves. Increase stake or add sponsor (ADR 007).")
    elif trust == "new":
        notes.append("New: visible in search with 'new' badge. Max 5 EUR/job for first 30 days.")

    return AgentRegisterResponse(
        did=did, trust_level=trust, webhook_secret=webhook_secret, registered_at=now, notes=notes
    )


@router.get("/{did}")
async def get_agent(did: str) -> dict[str, Any]:
    rec = _AGENTS.get(did)
    if not rec:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    return {k: v for k, v in rec.items() if k != "webhook_secret"}


@router.get("")
async def list_agents() -> dict[str, Any]:
    return {
        "total": len(_AGENTS),
        "agents": [{k: v for k, v in rec.items() if k != "webhook_secret"} for rec in _AGENTS.values()],
    }


@router.delete("/{did}")
async def deactivate_agent(did: str) -> dict[str, str]:
    if did not in _AGENTS:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    _AGENTS[did]["status"] = "archived"
    return {"did": did, "status": "archived"}
