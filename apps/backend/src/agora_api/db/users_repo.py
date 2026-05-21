"""Repository for users — Privy-authenticated humans on Agora (Sprint 10d).

A `User` row is created the first time a person logs in via Privy. We
also create a 1-1 "personal agent" record for that user so the existing
agent-centric flows (x402 jobs, listings as seller) keep working without
introducing a second principal type. The agent's `owner_did` matches the
user's `did`, and the agent's `did` is the same string — they are
deliberately one and the same identity. The user *is* an agent of type
'user' from the marketplace's point of view.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, AgentStatus, AgentType, TrustLevel, User


# ── DID generation ──────────────────────────────────────────────────


def did_for_privy_user(privy_user_id: str) -> str:
    """Derive a stable `did:agora:<16-bytes-base64url>` from a Privy id.

    Same Privy id → same DID, so re-login is idempotent. We hash so the
    raw Privy id (which Privy may treat as semi-secret) never appears in
    URLs or public payloads.
    """
    h = hashlib.sha256(privy_user_id.encode("utf-8")).digest()[:16]
    suffix = base64.urlsafe_b64encode(h).rstrip(b"=").decode()
    return f"did:agora:{suffix}"


# ── Lookups ─────────────────────────────────────────────────────────


async def get_by_privy_id(session: AsyncSession, privy_user_id: str) -> User | None:
    result = await session.execute(
        select(User).where(User.privy_user_id == privy_user_id)
    )
    return result.scalar_one_or_none()


async def get_by_did(session: AsyncSession, did: str) -> User | None:
    result = await session.execute(select(User).where(User.did == did))
    return result.scalar_one_or_none()


# ── Create / upsert ─────────────────────────────────────────────────


async def upsert_from_privy(
    session: AsyncSession,
    *,
    privy_user_id: str,
    email: str | None = None,
    primary_wallet: str | None = None,
) -> tuple[User, Agent]:
    """Find or create a User+Agent pair for a Privy-authenticated person.

    Returns (user, agent). The agent is the user's "personal" agent —
    the one whose DID is used as `requester_did` when this person buys
    something through the marketplace, and as `seller_did` when they
    list. Calling this on every login is safe (idempotent on
    `privy_user_id`).

    Subsequent calls update the user's email / primary_wallet if they
    changed in Privy (e.g. the user linked a new wallet). The agent's
    payout_wallet is only refreshed if it was empty (so a user-set value
    isn't clobbered).
    """
    user = await get_by_privy_id(session, privy_user_id)
    if user is not None:
        # Update mutable fields if Privy now reports a value we lacked.
        if email and not user.email:
            user.email = email
        if primary_wallet and not user.primary_wallet:
            user.primary_wallet = primary_wallet
        # Locate the personal agent.
        result = await session.execute(select(Agent).where(Agent.did == user.did))
        agent = result.scalar_one_or_none()
        if agent is None:
            # User row exists from an earlier-half-finished login. Build
            # the agent now so subsequent flows can rely on it.
            agent = await _create_personal_agent(
                session, user=user, primary_wallet=primary_wallet
            )
        elif primary_wallet and not agent.payout_wallet:
            agent.payout_wallet = primary_wallet
        await session.flush()
        return user, agent

    # First time we see this Privy user.
    did = did_for_privy_user(privy_user_id)
    user = User(
        did=did,
        email=email,
        settings={},
        privy_user_id=privy_user_id,
        primary_wallet=primary_wallet,
    )
    session.add(user)
    await session.flush()

    agent = await _create_personal_agent(
        session, user=user, primary_wallet=primary_wallet
    )
    return user, agent


async def _create_personal_agent(
    session: AsyncSession,
    *,
    user: User,
    primary_wallet: str | None,
) -> Agent:
    """Mint the personal Agent that represents this human on Agora."""
    webhook_secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(webhook_secret.encode("utf-8")).hexdigest()

    display_name = user.email or f"User {user.did.split(':')[-1][:8]}"
    agent = Agent(
        did=user.did,
        did_document={
            "id": user.did,
            "type": "user",
            "controller": user.did,
        },
        owner_user_id=user.id,
        owner_did=user.did,
        type=AgentType.user,
        name=display_name,
        description="Personal agent for a human user (created via Privy login).",
        capabilities=[],
        pricing={},
        constraints={},
        public_endpoint=None,
        stake_eur=Decimal("0"),
        sponsor_did=None,
        sponsor_signature=None,
        trust_level=TrustLevel.new,
        webhook_secret_hash=secret_hash,
        status=AgentStatus.active,
        payout_wallet=primary_wallet,
    )
    session.add(agent)
    await session.flush()
    return agent


# ── Public view ─────────────────────────────────────────────────────


def to_public_dict(user: User, agent: Agent | None = None) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "did": user.did,
        "email": user.email,
        "primary_wallet": user.primary_wallet,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "agent": (
            {
                "did": agent.did,
                "name": agent.name,
                "trust_level": (
                    agent.trust_level.value
                    if hasattr(agent.trust_level, "value")
                    else str(agent.trust_level)
                ),
                "payout_wallet": agent.payout_wallet,
            }
            if agent is not None
            else None
        ),
    }
