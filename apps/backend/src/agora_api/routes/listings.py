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

from ..config import get_settings
from ..db import agents_repo, listings_repo
from ..db.base import get_session
from ..db.models import ListingKind, ListingType
from ..rate_limit import limiter

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────


class ListingCreateRequest(BaseModel):
    seller_kind: str = Field(..., description="'agent' or 'user'")
    seller_did: str = Field(..., description="DID of the agent or user offering this listing")
    payout_wallet: str = Field(..., description="EVM address to receive USDC payout")
    listing_type: str = Field(..., description="'service' or 'digital_product'")
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(default="", max_length=10_000)
    category: str = Field(default="other", max_length=64)
    tags: list[str] = Field(default_factory=list)
    price_amount: str = Field(..., description="USDC amount, decimal string (e.g. '2.50')")
    price_currency: str = Field(default="USDC")
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
) -> dict[str, Any]:
    kind = _parse_kind(body.seller_kind)
    lt = _parse_type(body.listing_type)
    await _validate_seller(session, kind, body.seller_did)

    try:
        price = Decimal(body.price_amount)
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"invalid price_amount: {e}"
        ) from e
    if price <= 0:
        raise HTTPException(status_code=400, detail="price_amount must be > 0")

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
        seller_did=body.seller_did,
        payout_wallet=body.payout_wallet,
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
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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


@router.delete(
    "/{listing_id}",
    summary="Archive a listing (soft-delete)",
)
async def archive_listing(
    listing_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    # NOTE: no seller-auth check yet — Sprint 10d adds Privy auth that
    # verifies the caller actually owns the listing. Today this is open
    # by design (testnet, dev mode) so seed scripts and manual tooling
    # can clean up. Tighten before any production-like exposure.
    try:
        lid = uuid.UUID(listing_id)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"invalid listing id: {e}"
        ) from e
    listing = await listings_repo.get(session, lid)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"listing {listing_id} not found")
    await listings_repo.archive(session, listing)
    await session.commit()
    return {"id": listing_id, "status": "archived"}


# Suppress unused-import noise on settings — kept for future auth wiring.
_ = get_settings
