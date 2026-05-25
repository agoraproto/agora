"""Marketplace listings routes (Sprint 10).

The marketplace UI fetches from these endpoints to render the
browse-and-buy experience. Buying happens through the existing x402
endpoints (`/v1/x402/jobs`) — the Listing carries the information the
buyer needs to construct that POST.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user_optional
from ..config import get_settings
from ..db import agents_repo, jobs_repo, listings_repo
from ..db.base import get_session
from ..db.models import Agent, JobStatus, ListingKind, ListingType, User
from ..rate_limit import limiter

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────


class ListingCreateRequest(BaseModel):
    # AUTH-AWARE FIELDS (Sprint 18b doc clarification):
    # - Anonymous calls (no Privy bearer token): seller_kind, seller_did,
    #   AND payout_wallet are ALL required. Returns 400 if any is missing.
    # - Authed calls (Privy token in Authorization header): all three are
    #   ignored — the API forces seller_kind="user", seller_did=user.did,
    #   payout_wallet falls back to user.primary_wallet if absent.
    seller_kind: str | None = Field(
        default=None,
        description="'agent' or 'user'. Required when calling without a "
                    "Privy login. Ignored (forced to 'user') when authed.",
    )
    seller_did: str | None = Field(
        default=None,
        description="DID of the seller. Required when calling without a "
                    "Privy login. Ignored when authed.",
    )
    payout_wallet: str | None = Field(
        default=None,
        description="EVM address (0x…) where USDC payouts land. REQUIRED "
                    "for anonymous (non-authed) calls — first POST without "
                    "this field will 400. For authed calls falls back to "
                    "the user's primary_wallet from Privy.",
    )
    listing_type: str = Field(..., description="'service' or 'digital_product'")
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(default="", max_length=10_000)
    category: str = Field(default="other", max_length=64)
    tags: list[str] = Field(default_factory=list)
    price_amount: str = Field(
        ...,
        description="USDC amount as decimal string (e.g. '0.51', '2.50'). "
                    "On-chain min is 0 USDC (Sprint 16), but the buyer pays "
                    "0.1% platform fee + 10% insurance share of that fee.",
    )
    price_currency: str = Field(default="USDC", description="Always 'USDC' on Base Sepolia.")
    service_capability: str | None = None
    service_input_schema: dict[str, Any] | None = None
    digital_content_type: str | None = None
    digital_content: dict[str, Any] | None = None
    cover_image_url: str | None = None
    images: list[str] = Field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_kind(s: str) -> ListingKind:
    try:
        return ListingKind(s)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"seller_kind must be 'agent' or 'user', got {s!r}"
        ) from e


# ─── Test-data heuristic (Sprint 27a — audit finding #6) ────────────
# Demo seller DIDs and explicit Sprint-test listings are development
# artefacts that should not show up in the default marketplace view.
# Hidden by default; pass ?include_test=true to include them.

_DEMO_SELLER_PREFIXES = ("did:agora:demo_",)
_DEMO_TITLE_MARKERS = ("sprint 10d", "live test", "smoke test", "demo only")


def _is_test_listing(listing: Any) -> bool:
    seller = (getattr(listing, "seller_did", "") or "").lower()
    if any(seller.startswith(p) for p in _DEMO_SELLER_PREFIXES):
        return True
    title = (getattr(listing, "title", "") or "").lower()
    return any(m in title for m in _DEMO_TITLE_MARKERS)


def _parse_type(s: str) -> ListingType:
    try:
        return ListingType(s)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"listing_type must be 'service' or 'digital_product', got {s!r}",
        ) from e


async def _validate_seller(session: AsyncSession, kind: ListingKind, did: str) -> None:
    if kind == ListingKind.agent:
        if await agents_repo.get_by_did(session, did) is None:
            raise HTTPException(
                status_code=400, detail=f"agent seller {did} not found on Agora"
            )
    # For user sellers we don't enforce a DB row yet — Privy auth (Sprint
    # 10d) will gate creation through the UI. For now, allow any DID
    # string so we can seed listings against synthetic user DIDs.


# ── Routes ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a marketplace listing (seller-side)",
)
@limiter.limit("30/minute")
async def create_listing(
    request: Request,
    body: ListingCreateRequest,
    session: AsyncSession = Depends(get_session),
    principal: tuple[User, Agent] | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    # ── Auth-aware seller resolution ──
    # If the caller is a logged-in human, the seller is forced to be
    # them — they cannot create a listing under someone else's DID.
    # If unauthed, the SDK / seed flow must explicitly supply all
    # seller fields and seller_kind has to be 'agent' (humans must
    # login first).
    if principal is not None:
        user, _user_agent = principal
        seller_kind_str = "user"
        seller_did = user.did
        payout_wallet = body.payout_wallet or user.primary_wallet
        if not payout_wallet:
            raise HTTPException(
                status_code=400,
                detail=(
                    "no payout_wallet on file — link a wallet via Privy or "
                    "pass payout_wallet in the request body."
                ),
            )
    else:
        # ── Anonymous / legacy SDK path ──
        # Tests and SDK callers can hit this endpoint without auth as
        # long as they explicitly provide every seller field. There's
        # no DID-ownership check on `seller_did` for anonymous calls
        # — a future sprint will add DID-signature verification so
        # agents prove they own their DID. For now, anonymous user-DID
        # listings are tolerated (legacy) and rate-limited against
        # spam. Authed callers go through the strict path above.
        if not body.seller_kind or not body.seller_did or not body.payout_wallet:
            raise HTTPException(
                status_code=400,
                detail=(
                    "create_listing requires seller_kind, seller_did and "
                    "payout_wallet — or login via Privy to have them set "
                    "from your authenticated session."
                ),
            )
        seller_kind_str = body.seller_kind
        seller_did = body.seller_did
        payout_wallet = body.payout_wallet

    kind = _parse_kind(seller_kind_str)
    lt = _parse_type(body.listing_type)
    await _validate_seller(session, kind, seller_did)

    try:
        price = Decimal(body.price_amount)
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"invalid price_amount: {e}"
        ) from e
    if price <= 0:
        raise HTTPException(status_code=400, detail="price_amount must be > 0")
    # Sprint 16: removed the previous price > 0.50 USDC requirement.
    # The on-chain contract now has minFee = 0 and feeBps = 10 (0.10%),
    # designed for high-volume micro-transactions between AI agents.
    # Listings as low as 0.001 USDC are buyable.

    if lt == ListingType.service and not body.service_capability:
        raise HTTPException(
            status_code=400, detail="service listings require `service_capability`"
        )
    if lt == ListingType.digital_product and not body.digital_content:
        raise HTTPException(
            status_code=400, detail="digital_product listings require `digital_content`"
        )

    listing = await listings_repo.create(
        session,
        seller_kind=kind,
        seller_did=seller_did,
        payout_wallet=payout_wallet,
        listing_type=lt,
        title=body.title,
        description=body.description,
        category=body.category,
        tags=body.tags,
        price_amount=price,
        price_currency=body.price_currency,
        service_capability=body.service_capability,
        service_input_schema=body.service_input_schema,
        digital_content_type=body.digital_content_type,
        digital_content=body.digital_content,
        cover_image_url=body.cover_image_url,
        images=body.images,
    )
    await session.commit()
    return listings_repo.to_public_dict(listing)


@router.get(
    "",
    summary="Browse marketplace listings (filter + paginate)",
)
async def list_listings(
    category: str | None = None,
    listing_type: str | None = None,
    seller_kind: str | None = None,
    seller_did: str | None = None,
    q: str | None = None,
    max_price: str | None = None,
    limit: int = 60,
    offset: int = 0,
    include_test: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Browse marketplace listings.

    By default demo-seller listings and Sprint-test listings are hidden
    so the marketplace looks like production rather than a half-cleaned
    staging environment (Sprint 27a — audit finding #6). Pass
    `?include_test=true` to include them.
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be in 1..200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    parsed_max_price: Decimal | None = None
    if max_price is not None:
        try:
            parsed_max_price = Decimal(max_price)
        except (InvalidOperation, ValueError) as e:
            raise HTTPException(
                status_code=400, detail=f"invalid max_price: {e}"
            ) from e

    listings = await listings_repo.search(
        session,
        category=category,
        listing_type=_parse_type(listing_type) if listing_type else None,
        seller_kind=_parse_kind(seller_kind) if seller_kind else None,
        seller_did=seller_did,
        free_text=q,
        max_price=parsed_max_price,
        limit=limit,
        offset=offset,
    )
    if not include_test:
        listings = [L for L in listings if not _is_test_listing(L)]
    return {
        "total": len(listings),
        "limit": limit,
        "offset": offset,
        "listings": [listings_repo.to_public_dict(L) for L in listings],
    }


@router.get(
    "/{listing_id}",
    summary="Get a single listing by id",
)
async def get_listing(
    listing_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        lid = uuid.UUID(listing_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"invalid listing id: {e}"
        ) from e
    listing = await listings_repo.get(session, lid)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
    return listings_repo.to_public_dict(listing)


@router.get(
    "/{listing_id}/delivery",
    summary="Get the digital deliverable for a paid listing purchase",
)
async def get_delivery(
    listing_id: str,
    job_id: str,
    session: AsyncSession = Depends(get_session),
    principal: tuple[User, Agent] | None = Depends(get_current_user_optional),
) -> dict[str, Any]:
    """Return a marketplace listing's deliverable to the legitimate buyer.

    Sprint 10d: this is now gated by Privy auth. The caller must be
    logged in AND must be the buyer (i.e. the `requester_agent.owner_did`
    of the Job must equal the user's DID). Anonymous calls receive 401.

    For agent-driven buys (SDK flow, not via the web UI) we fall back
    to the legacy "knowledge of the (listing_id, job_id) pair" model:
    if the job's requester is an agent of type 'service' (not 'user'),
    the agent's holder of the URL is trusted. This will tighten further
    once agents authenticate via signed DID assertions.

    Behaviour:

      * Looks up the Listing + Job; both must exist and the Job must be
        linked back to the Listing via `Job.listing_id`.
      * For DIGITAL PRODUCT listings: returns `digital_content` as soon
        as the Job is at least in `offered` status (i.e. escrow funded
        on-chain). The seller's USDC is still locked in escrow until the
        buyer approves — this is intentional so the buyer can preview
        the artifact before releasing payment.
      * For SERVICE listings: returns the Job's `result` (the artifact
        the provider submitted via submitResult). Only available when
        the Job is in `submitted` or `completed` status.
      * 404 if either is missing or the pair doesn't match.
      * 409 if the Job hasn't reached a deliverable state yet.
    """
    try:
        lid = uuid.UUID(listing_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid listing id: {e}") from e
    try:
        jid = uuid.UUID(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid job id: {e}") from e

    listing = await listings_repo.get(session, lid)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")

    job = await jobs_repo.get(session, jid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.listing_id != lid:
        raise HTTPException(
            status_code=404,
            detail=f"job {job_id} is not linked to listing {listing_id}",
        )

    # ── Buyer authorisation (Sprint 10d) ──
    # The job's requester_agent is the buyer's identity on Agora. For
    # human buyers it's their personal agent, whose owner_did == user.did.
    requester_agent = await agents_repo.get_by_id(session, job.requester_agent_id)
    if requester_agent is None:
        # Shouldn't happen — Job FK guarantees the row exists — but
        # avoid leaking content if it does.
        raise HTTPException(status_code=404, detail="job requester missing")

    if requester_agent.type.value == "user" or str(requester_agent.type) == "user":
        # Buy was made through the web UI by a logged-in human. Require
        # that same human to be calling us now.
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="delivery requires Privy login (this purchase was made by a logged-in user)",
            )
        user, _ = principal
        if requester_agent.owner_did != user.did:
            raise HTTPException(
                status_code=403,
                detail="you are not the buyer of this order",
            )
    # else: agent-driven buy → legacy path. SDK auth lands in a later sprint.

    # Status-gating per listing_type.
    lt = (
        listing.listing_type.value
        if hasattr(listing.listing_type, "value")
        else str(listing.listing_type)
    )
    status_value = (
        job.status.value if hasattr(job.status, "value") else str(job.status)
    )

    if lt == "digital_product":
        # Buyer-paid (escrow funded) is enough — the artifact was
        # pre-set by the seller at listing time and doesn't depend on
        # job state advancing further.
        if status_value not in ("offered", "submitted", "completed"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"job is in '{status_value}' state — deliverable is "
                    f"available once escrow has been funded ('offered')."
                ),
            )
        return {
            "listing_id": str(listing.id),
            "job_id": str(job.id),
            "kind": "digital_product",
            "delivery_status": status_value,
            "content_type": listing.digital_content_type,
            "content": listing.digital_content,
            "note": (
                "Funds are still in escrow until you approve the job on-chain. "
                "Call POST /v1/x402/jobs/{job_id}/approve to release."
                if status_value == "offered"
                else None
            ),
        }

    # Services: result must have been submitted by the provider.
    if status_value not in ("submitted", "completed"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"job is in '{status_value}' state — service result not yet "
                f"submitted. Wait for the provider to call submitResult."
            ),
        )
    return {
        "listing_id": str(listing.id),
        "job_id": str(job.id),
        "kind": "service",
        "delivery_status": status_value,
        "content_type": "application/json",
        "content": job.result,
        "note": (
            "Result delivered. Call POST /v1/x402/jobs/{job_id}/approve to "
            "release the seller's USDC and close the job."
            if status_value == "submitted"
            else None
        ),
    }


@router.delete(
    "/{listing_id}",
    summary="Archive a listing (soft-delete)",
)
async def archive_listing(
    listing_id: str,
    session: AsyncSession = Depends(get_session),
    principal: tuple[User, Agent] | None = Depends(get_current_user_optional),
) -> dict[str, str]:
    """Sprint 10d: human-listing owners must authenticate to archive.

    Agent-listings (seller_kind='agent') are still archivable without
    auth — a future sprint will add agent API-key / DID-signature
    middleware so the agent's owner can archive their own listings.
    """
    try:
        lid = uuid.UUID(listing_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"invalid listing id: {e}"
        ) from e
    listing = await listings_repo.get(session, lid)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")

    if listing.seller_kind == ListingKind.user:
        if principal is None:
            raise HTTPException(
                status_code=401, detail="user-owned listing — login required"
            )
        user, _ = principal
        if listing.seller_did != user.did:
            raise HTTPException(
                status_code=403,
                detail="only the owning user can archive this listing",
            )
    # else: agent listing — open until per-agent auth lands.

    await listings_repo.archive(session, listing)
    await session.commit()
    return {"id": listing_id, "status": "archived"}


# Suppress unused-import noise on settings — kept for future auth wiring.
_ = get_settings
