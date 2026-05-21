"""Authenticated-user routes (Sprint 10d).

Tiny surface — Privy holds the heavy lifting (login UI, session, JWT
issuance). On our side we just:

  * `POST /v1/auth/sync` — called by the frontend right after Privy
    finishes login. Idempotently creates the `User` + personal `Agent`
    rows and returns them. Body may optionally carry profile hints
    (email, primary_wallet, display_name) when they're available
    client-side but not in the JWT.

  * `GET /v1/auth/me` — returns the current logged-in user. 401 if
    no token. Used by the frontend on page load to decide whether to
    show "Login" or "Logged in as …".

  * `GET /v1/auth/my-listings` — returns all listings owned by the
    current user. Powers the seller dashboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import listings_repo, users_repo
from ..db.base import get_session
from ..db.models import Agent, Listing, ListingStatus, User

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────


class AuthSyncBody(BaseModel):
    email: str | None = Field(
        default=None, description="Email returned by Privy if user used email login."
    )
    primary_wallet: str | None = Field(
        default=None,
        description=(
            "EVM address of the user's Privy embedded wallet (or linked external "
            "wallet). Becomes the default payout_wallet for new listings."
        ),
    )
    display_name: str | None = Field(
        default=None,
        description="Optional human-readable name. Updates the personal agent.",
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.post("/sync", summary="Upsert the current user from Privy session data")
async def sync_user(
    body: AuthSyncBody,
    principal: tuple[User, Agent] = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Apply optional profile hints from the client to the user row.

    Auth dependency (`get_current_user`) has already upserted the user
    + agent with whatever was forwarded as request headers. This
    endpoint lets the client provide richer data in the POST body
    (more friendly than headers) and then re-reads the canonical state.
    """
    user, agent = principal
    dirty = False
    if body.email and user.email != body.email:
        user.email = body.email
        dirty = True
    if body.primary_wallet and user.primary_wallet != body.primary_wallet:
        user.primary_wallet = body.primary_wallet
        dirty = True
        if not agent.payout_wallet:
            agent.payout_wallet = body.primary_wallet
    if body.display_name and agent.name != body.display_name:
        agent.name = body.display_name
        dirty = True
    if dirty:
        await session.commit()
        await session.refresh(user)
        await session.refresh(agent)
    return users_repo.to_public_dict(user, agent)


@router.get("/me", summary="Get the currently logged-in user")
async def get_me(
    principal: tuple[User, Agent] = Depends(get_current_user),
) -> dict[str, Any]:
    user, agent = principal
    return users_repo.to_public_dict(user, agent)


@router.get("/my-listings", summary="List all marketplace listings owned by me")
async def my_listings(
    principal: tuple[User, Agent] = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    include_archived: bool = False,
) -> dict[str, Any]:
    user, _ = principal
    stmt = select(Listing).where(Listing.seller_did == user.did)
    if not include_archived:
        stmt = stmt.where(Listing.status != ListingStatus.archived)
    stmt = stmt.order_by(Listing.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "total": len(rows),
        "listings": [listings_repo.to_public_dict(L) for L in rows],
    }
