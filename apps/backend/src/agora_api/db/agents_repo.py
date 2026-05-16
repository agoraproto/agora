"""Repository for agent persistence (ADR 006 self-registration)."""

from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AgentStatus, TrustLevel

# Trust levels visible in default search (excludes probation by design - ADR 007).
_PUBLIC_TRUST_LEVELS = (TrustLevel.new, TrustLevel.verified, TrustLevel.trusted)


def _hash_secret(secret: str) -> str:
    """SHA-256 of webhook secret. Plain secret never stored in DB."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def trust_level_from(stake: Decimal, has_sponsor: bool) -> TrustLevel:
    """ADR 007: stake / sponsor -> trust level mapping."""
    if has_sponsor:
        return TrustLevel.new
    if stake >= Decimal("100"):
        return TrustLevel.verified
    if stake >= Decimal("25"):
        return TrustLevel.new
    return TrustLevel.probation


async def get_by_did(session: AsyncSession, did: str) -> Agent | None:
    result = await session.execute(select(Agent).where(Agent.did == did))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Agent]:
    result = await session.execute(select(Agent).order_by(Agent.created_at))
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    *,
    did: str,
    did_document: dict[str, Any],
    name: str,
    description: str,
    owner_did: str,
    capabilities: list[dict[str, Any]],
    pricing: dict[str, Any],
    endpoint_url: str,
    stake_eur: Decimal,
    sponsor_did: str | None,
    sponsor_signature: str | None,
) -> tuple[Agent, str]:
    """Insert a new agent. Returns (agent, plain_webhook_secret).

    The plain secret is returned exactly once; only its hash is persisted.
    """
    trust = trust_level_from(stake_eur, sponsor_did is not None)
    webhook_secret = secrets.token_urlsafe(32)

    agent = Agent(
        did=did,
        did_document=did_document,
        owner_user_id=None,
        owner_did=owner_did,
        name=name,
        description=description,
        capabilities=capabilities,
        pricing=pricing,
        constraints={},
        public_endpoint=endpoint_url or None,
        stake_eur=stake_eur,
        sponsor_did=sponsor_did,
        sponsor_signature=sponsor_signature,
        trust_level=trust,
        webhook_secret_hash=_hash_secret(webhook_secret),
        status=AgentStatus.active,
    )
    session.add(agent)
    await session.flush()
    return agent, webhook_secret


async def archive(session: AsyncSession, agent: Agent) -> None:
    agent.status = AgentStatus.archived
    await session.flush()


def _base_price(pricing: dict[str, Any]) -> Decimal | None:
    """Best-effort extraction of an agent's headline price for filtering.

    Returns None if pricing is empty or has no parseable base_price.
    """
    if not isinstance(pricing, dict):
        return None
    candidates = []
    if "base_price" in pricing:
        candidates.append(pricing["base_price"])
    if "models" in pricing and isinstance(pricing["models"], list):
        for m in pricing["models"]:
            if isinstance(m, dict) and "base_price" in m:
                candidates.append(m["base_price"])
            elif isinstance(m, dict) and "amount" in m:
                candidates.append(m["amount"])
    for c in candidates:
        try:
            return Decimal(str(c))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return None


def _capabilities_match(capabilities: list[dict[str, Any]], wanted: str) -> bool:
    """Does this agent declare a capability of the given type?"""
    if not isinstance(capabilities, list):
        return False
    needle = wanted.lower()
    for c in capabilities:
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type", "")).lower()
        if ctype == needle:
            return True
    return False


async def search(
    session: AsyncSession,
    *,
    capability: str | None = None,
    text: str | None = None,
    max_price: Decimal | None = None,
    min_trust: TrustLevel | None = None,
    include_probation: bool = False,
    limit: int = 50,
) -> list[Agent]:
    """DB-side filter on simple columns, then in-Python filter on JSON pricing
    and capabilities (works on both Postgres and SQLite).

    Probation-level agents are hidden by default (ADR 007).
    """
    stmt = select(Agent).where(Agent.status == AgentStatus.active)

    # Trust gate (ADR 007)
    if not include_probation:
        stmt = stmt.where(Agent.trust_level.in_(_PUBLIC_TRUST_LEVELS))
    if min_trust is not None:
        ordered = [TrustLevel.probation, TrustLevel.new, TrustLevel.verified, TrustLevel.trusted]
        threshold_idx = ordered.index(min_trust)
        allowed = ordered[threshold_idx:]
        stmt = stmt.where(Agent.trust_level.in_(allowed))

    # Free-text on name + description (LIKE works on Postgres and SQLite)
    if text:
        pat = f"%{text.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Agent.name.ilike(pat),
                Agent.description.ilike(pat),
            )
        )

    stmt = stmt.order_by(Agent.trust_level.desc(), Agent.created_at.desc()).limit(limit * 4)
    result = await session.execute(stmt)
    candidates = list(result.scalars().all())

    # Capability & price refinement done in Python because JSON-querying
    # differs between SQLite and Postgres. At scale this gets pushed down
    # to pgvector / JSONB indexes in Sprint 3+.
    filtered: list[Agent] = []
    for a in candidates:
        if capability is not None and not _capabilities_match(a.capabilities or [], capability):
            continue
        if max_price is not None:
            price = _base_price(a.pricing or {})
            if price is None or price > max_price:
                continue
        filtered.append(a)
        if len(filtered) >= limit:
            break
    return filtered


def to_public_dict(agent: Agent) -> dict[str, Any]:
    """Public-facing JSON representation. Never includes webhook_secret_hash."""
    return {
        "did": agent.did,
        "name": agent.name,
        "description": agent.description,
        "owner_did": agent.owner_did,
        "capabilities": agent.capabilities or [],
        "pricing": agent.pricing or {},
        "constraints": agent.constraints or {},
        "endpoint_url": agent.public_endpoint or "",
        "stake_eur": str(agent.stake_eur or Decimal("0")),
        "sponsor": (
            {"sponsor_did": agent.sponsor_did, "signature": agent.sponsor_signature}
            if agent.sponsor_did
            else None
        ),
        "trust_level": agent.trust_level.value if agent.trust_level else None,
        "status": agent.status.value if agent.status else None,
        "registered_at": agent.created_at.isoformat() if agent.created_at else None,
    }


def to_match_dict(agent: Agent) -> dict[str, Any]:
    """Compact view returned by /v1/search and /v1/match."""
    return {
        "did": agent.did,
        "name": agent.name,
        "description": agent.description,
        "capabilities": [c.get("type") for c in (agent.capabilities or []) if isinstance(c, dict)],
        "pricing": agent.pricing or {},
        "trust_level": agent.trust_level.value if agent.trust_level else None,
        "endpoint_url": agent.public_endpoint or "",
    }
