"""Repository helpers for Sprint 31 RFQ service requests and bids."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Bid,
    BidStatus,
    ServiceRequest,
    ServiceRequestStatus,
    SignedAction,
)


async def create_request(
    session: AsyncSession,
    *,
    buyer_did: str,
    title: str,
    description: str,
    capability: str | None,
    constraints: dict[str, Any],
    max_price_micro_usdc: int,
    currency: str,
    deadline: datetime | None,
) -> ServiceRequest:
    row = ServiceRequest(
        id=uuid.uuid4(),
        buyer_did=buyer_did,
        title=title,
        description=description,
        capability=capability,
        constraints=constraints,
        max_price_micro_usdc=max_price_micro_usdc,
        currency=currency,
        deadline=deadline,
        status=ServiceRequestStatus.open,
    )
    session.add(row)
    await session.flush()
    return row


async def get_request(session: AsyncSession, request_id: uuid.UUID) -> ServiceRequest | None:
    result = await session.execute(select(ServiceRequest).where(ServiceRequest.id == request_id))
    return result.scalar_one_or_none()


async def list_requests(
    session: AsyncSession,
    *,
    status: ServiceRequestStatus | None = ServiceRequestStatus.open,
    capability: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ServiceRequest]:
    stmt = select(ServiceRequest)
    if status is not None:
        stmt = stmt.where(ServiceRequest.status == status)
    if capability:
        stmt = stmt.where(ServiceRequest.capability == capability)
    stmt = stmt.order_by(ServiceRequest.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def create_bid(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    provider_did: str,
    price_micro_usdc: int,
    currency: str,
    message: str,
    signed_payload: dict[str, Any],
    signature: str,
    nonce: str,
    bid_hash: str,
    expires_at: datetime,
) -> Bid:
    row = Bid(
        id=uuid.uuid4(),
        request_id=request_id,
        provider_did=provider_did,
        price_micro_usdc=price_micro_usdc,
        currency=currency,
        message=message,
        signed_payload=signed_payload,
        signature=signature,
        nonce=nonce,
        bid_hash=bid_hash,
        expires_at=expires_at,
        status=BidStatus.pending,
    )
    session.add(row)
    await session.flush()
    return row


async def get_bid(session: AsyncSession, bid_id: uuid.UUID) -> Bid | None:
    result = await session.execute(select(Bid).where(Bid.id == bid_id))
    return result.scalar_one_or_none()


async def list_bids_for_request(session: AsyncSession, request_id: uuid.UUID) -> list[Bid]:
    result = await session.execute(
        select(Bid).where(Bid.request_id == request_id).order_by(Bid.created_at.desc())
    )
    return list(result.scalars().all())


async def count_bids_for_request(session: AsyncSession, request_id: uuid.UUID) -> int:
    result = await session.execute(select(func.count()).select_from(Bid).where(Bid.request_id == request_id))
    return int(result.scalar_one())


async def count_bids_for_provider(
    session: AsyncSession, *, request_id: uuid.UUID, provider_did: str
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Bid)
        .where(Bid.request_id == request_id, Bid.provider_did == provider_did)
    )
    return int(result.scalar_one())


async def nonce_exists(
    session: AsyncSession, *, request_id: uuid.UUID, provider_did: str, nonce: str
) -> bool:
    result = await session.execute(
        select(Bid.id).where(
            Bid.request_id == request_id,
            Bid.provider_did == provider_did,
            Bid.nonce == nonce,
        )
    )
    return result.scalar_one_or_none() is not None


async def accept_bid(
    session: AsyncSession,
    *,
    request: ServiceRequest,
    bid: Bid,
) -> None:
    request.status = ServiceRequestStatus.accepted
    request.accepted_bid_id = bid.id
    bid.status = BidStatus.accepted
    await session.flush()


def request_to_public_dict(row: ServiceRequest, *, bid_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "buyer_did": row.buyer_did,
        "title": row.title,
        "description": row.description,
        "capability": row.capability,
        "constraints": row.constraints or {},
        "max_price_micro_usdc": row.max_price_micro_usdc,
        "currency": row.currency,
        "deadline": row.deadline.isoformat() if row.deadline else None,
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        "accepted_bid_id": str(row.accepted_bid_id) if row.accepted_bid_id else None,
        "bid_count": bid_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def bid_to_public_dict(row: Bid) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "request_id": str(row.request_id),
        "provider_did": row.provider_did,
        "price_micro_usdc": row.price_micro_usdc,
        "currency": row.currency,
        "message": row.message,
        "nonce": row.nonce,
        "bid_hash": row.bid_hash,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def record_signed_action(
    session: AsyncSession,
    *,
    actor_did: str,
    intent: str,
    nonce: str,
) -> bool:
    """Atomically reserve a (actor_did, intent, nonce) triple.

    Returns True if the row was inserted (i.e. this nonce is fresh).
    Returns False if the unique constraint rejected the insert (replay).

    Caller commits later as part of the surrounding transaction; we use
    a SAVEPOINT (nested) so a constraint violation doesn't poison the
    outer transaction. Backend callers should treat False as "replay,
    return HTTP 409".
    """
    row = SignedAction(actor_did=actor_did, intent=intent, nonce=nonce)
    sp = await session.begin_nested()
    session.add(row)
    try:
        await sp.commit()
    except IntegrityError:
        await sp.rollback()
        return False
    return True
