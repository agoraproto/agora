"""Repository for agent persistence (ADR 006 self-registration)."""

from __future__ import annotations

import hashlib
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AgentStatus, TrustLevel


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
