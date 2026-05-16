"""Capability discovery routes (Spec §6.3, §8.1).

DB-backed search. Probation-level agents are hidden by default (ADR 007).
Semantic / vector search comes later via pgvector — for Sprint 2 this is
a simple structured filter.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import agents_repo
from ..db.base import get_session
from ..db.models import TrustLevel

router = APIRouter()


@router.get("/search", summary="Search agents by capability and filters")
async def search_agents(
    capability: str | None = Query(None, examples=["LegalTranslation"]),
    text: str | None = Query(None, description="Free-text match on name and description"),
    max_price: str | None = Query(None, description="Decimal EUR price ceiling"),
    min_trust: str | None = Query(None, description="Minimum trust level: new|verified|trusted"),
    include_probation: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    parsed_max_price: Decimal | None = None
    if max_price is not None:
        try:
            parsed_max_price = Decimal(max_price)
        except (InvalidOperation, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"invalid max_price: {e}") from e

    parsed_min_trust: TrustLevel | None = None
    if min_trust is not None:
        try:
            parsed_min_trust = TrustLevel(min_trust)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid min_trust: {e}") from e

    matches = await agents_repo.search(
        session,
        capability=capability,
        text=text,
        max_price=parsed_max_price,
        min_trust=parsed_min_trust,
        include_probation=include_probation,
        limit=limit,
    )
    return {
        "total": len(matches),
        "matches": [agents_repo.to_match_dict(a) for a in matches],
    }


class MatchRequest(BaseModel):
    task: str = Field(..., description="Natural-language task description")
    capability: str | None = Field(
        None, description="Optional capability hint; if omitted the task is used as free text"
    )
    budget: str | None = None
    limit: int = 10


@router.post("/match", summary="Find best-matching agents for a task description")
async def match_agents(
    payload: MatchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """In Sprint 2 this is a thin wrapper over /search.

    In Sprint 4 it can call an LLM to extract structured filters from the
    task description before delegating to the same repository search.
    """
    parsed_budget: Decimal | None = None
    if payload.budget is not None:
        try:
            parsed_budget = Decimal(payload.budget)
        except (InvalidOperation, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"invalid budget: {e}") from e

    matches = await agents_repo.search(
        session,
        capability=payload.capability,
        text=payload.task if payload.capability is None else None,
        max_price=parsed_budget,
        limit=payload.limit,
    )
    return {
        "total": len(matches),
        "matches": [agents_repo.to_match_dict(a) for a in matches],
    }


@router.get("/capabilities", summary="List capability taxonomy")
async def list_capabilities() -> dict[str, Any]:
    """Return the current capability taxonomy.

    Static curated tree for MVP (see Spec §6.3). In Sprint 4 it becomes
    dynamic (community-extensible via PR process, Spec §21.5).
    """
    return {
        "capabilities": [
            {
                "name": "Translation",
                "children": ["LegalTranslation", "MedicalTranslation", "LiteraryTranslation"],
            },
            {"name": "Verification", "children": ["FactChecking", "CodeReview", "MathProof"]},
            {"name": "Generation", "children": ["TextGeneration", "ImageGeneration", "CodeGeneration"]},
            {"name": "Analysis", "children": []},
            {"name": "Negotiation", "children": []},
            {"name": "Research", "children": []},
            {"name": "Echo", "children": []},
        ]
    }
