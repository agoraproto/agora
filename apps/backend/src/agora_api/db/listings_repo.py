"""Repository for marketplace Listings (Sprint 10)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Listing, ListingKind, ListingStatus, ListingType


async def get(session: AsyncSession, listing_id: uuid.UUID) -> Listing | None:
    result = await session.execute(select(Listing).where(Listing.id == listing_id))
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    seller_kind: ListingKind,
    seller_did: str,
    payout_wallet: str,
    listing_type: ListingType,
    title: str,
    description: str,
    category: str,
    tags: list[str],
    price_amount: Decimal,
    price_currency: str = "USDC",
    service_capability: str | None = None,
    service_input_schema: dict[str, Any] | None = None,
    digital_content_type: str | None = None,
    digital_content: dict[str, Any] | None = None,
    cover_image_url: str | None = None,
    images: list[str] | None = None,
) -> Listing:
    listing = Listing(
        id=uuid.uuid4(),
        seller_kind=seller_kind,
        seller_did=seller_did,
        payout_wallet=payout_wallet,
        listing_type=listing_type,
        title=title,
        description=description,
        category=category,
        tags=tags,
        price_amount=price_amount,
        price_currency=price_currency,
        service_capability=service_capability,
        service_input_schema=service_input_schema,
        digital_content_type=digital_content_type,
        digital_content=digital_content,
        cover_image_url=cover_image_url,
        images=images or [],
        status=ListingStatus.active,
    )
    session.add(listing)
    await session.flush()
    return listing


async def search(
    session: AsyncSession,
    *,
    category: str | None = None,
    listing_type: ListingType | None = None,
    seller_kind: ListingKind | None = None,
    seller_did: str | None = None,
    free_text: str | None = None,
    max_price: Decimal | None = None,
    only_active: bool = True,
    limit: int = 60,
    offset: int = 0,
) -> list[Listing]:
    q = select(Listing)
    if only_active:
        q = q.where(Listing.status == ListingStatus.active)
    if category:
        q = q.where(Listing.category == category)
    if listing_type:
        q = q.where(Listing.listing_type == listing_type)
    if seller_kind:
        q = q.where(Listing.seller_kind == seller_kind)
    if seller_did:
        q = q.where(Listing.seller_did == seller_did)
    if max_price is not None:
        q = q.where(Listing.price_amount <= max_price)
    if free_text:
        pat = f"%{free_text}%"
        q = q.where(
            or_(
                Listing.title.ilike(pat),
                Listing.description.ilike(pat),
            )
        )
    q = q.order_by(Listing.sales_count.desc(), Listing.created_at.desc())
    q = q.limit(limit).offset(offset)
    result = await session.execute(q)
    return list(result.scalars().all())


async def archive(session: AsyncSession, listing: Listing) -> None:
    listing.status = ListingStatus.archived
    await session.flush()


async def increment_sales(session: AsyncSession, listing: Listing) -> None:
    """Called once a paid order has been fully released to the seller."""
    listing.sales_count = (listing.sales_count or 0) + 1
    await session.flush()


def to_public_dict(listing: Listing) -> dict[str, Any]:
    """Public-facing JSON for marketplace UI. Strips internals."""
    return {
        "id": str(listing.id),
        "seller_kind": (
            listing.seller_kind.value
            if hasattr(listing.seller_kind, "value")
            else str(listing.seller_kind)
        ),
        "seller_did": listing.seller_did,
        "payout_wallet": listing.payout_wallet,
        "listing_type": (
            listing.listing_type.value
            if hasattr(listing.listing_type, "value")
            else str(listing.listing_type)
        ),
        "title": listing.title,
        "description": listing.description,
        "category": listing.category,
        "tags": listing.tags or [],
        "price_amount": str(listing.price_amount),
        "price_currency": listing.price_currency,
        "service_capability": listing.service_capability,
        "service_input_schema": listing.service_input_schema,
        "digital_content_type": listing.digital_content_type,
        # NOTE: `digital_content` is intentionally NOT exposed in the
        # public dict. It's the deliverable — buyers receive it only after
        # successful x402 payment + approval. The marketplace UI shows a
        # description / preview instead.
        "cover_image_url": listing.cover_image_url,
        "images": listing.images or [],
        "status": (
            listing.status.value if hasattr(listing.status, "value") else str(listing.status)
        ),
        "sales_count": listing.sales_count,
        "rating_score": (
            str(listing.rating_score) if listing.rating_score is not None else None
        ),
        "rating_count": listing.rating_count,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }
