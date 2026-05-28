"""Sprint 31: RFQ (Request for Quote) endpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import agents_repo, rfq_repo
from ..db.base import get_session
from ..db.models import Agent, ServiceRequestStatus
from ..rate_limit import limiter
from ..sponsor import SponsorshipInvalid, extract_verify_key_from_did_document
from ..webhooks.delivery import enqueue_for_agent

router = APIRouter()

MAX_PRICE_MICRO_USDC = 10_000  # 0.01 USDC, in micro-USDC.
MAX_BIDS_PER_AGENT_PER_REQUEST = 3
MAX_BIDS_PER_REQUEST = 50
TIMESTAMP_WINDOW_SECONDS = 120


class CreateRequestBody(BaseModel):
    buyer_did: str
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(default="", max_length=2_000)
    capability: str | None = Field(default=None, max_length=64)
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_price_micro_usdc: int = Field(..., ge=0, le=MAX_PRICE_MICRO_USDC)
    currency: str = Field(default="USDC", max_length=8)
    deadline: datetime | None = None


class CreateBidBody(BaseModel):
    provider_did: str
    price_micro_usdc: int = Field(..., ge=0, le=MAX_PRICE_MICRO_USDC)
    currency: str = Field(default="USDC", max_length=8)
    message: str = Field(default="", max_length=1_000)
    signed_payload: dict[str, Any]
    signature: str
    nonce: str = Field(..., min_length=8, max_length=128)
    expires_at: datetime


class AcceptBidBody(BaseModel):
    buyer_did: str
    bid_hash: str | None = Field(default=None, min_length=64, max_length=64)


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def bid_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


async def _load_agent_or_404(session: AsyncSession, did: str) -> Agent:
    agent = await agents_repo.get_by_did(session, did)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent {did} not found")
    return agent


def _parse_request_id(request_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(request_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid request id: {e}") from e


def _parse_bid_id(bid_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(bid_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid bid id: {e}") from e


def _require_usdc(currency: str) -> None:
    if currency != "USDC":
        raise HTTPException(status_code=400, detail="currency must be USDC")


def _require_fresh_timestamp(payload: dict[str, Any]) -> None:
    raw = payload.get("timestamp")
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="signed_payload.timestamp is required")
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"bad timestamp: {e}") from e
    now = datetime.now(UTC)
    if abs(now - ts) > timedelta(seconds=TIMESTAMP_WINDOW_SECONDS):
        raise HTTPException(status_code=400, detail="signed_payload.timestamp outside replay window")


def _require_payload_matches(
    *,
    payload: dict[str, Any],
    request_id: uuid.UUID,
    provider_did: str,
    price_micro_usdc: int,
    currency: str,
    nonce: str,
    expires_at: datetime,
) -> None:
    expected = {
        "request_id": str(request_id),
        "provider_did": provider_did,
        "price_micro_usdc": price_micro_usdc,
        "currency": currency,
        "nonce": nonce,
        "expires_at": expires_at.isoformat(),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise HTTPException(
                status_code=400,
                detail=f"signed_payload.{key} must match request body",
            )
    _require_fresh_timestamp(payload)


def _verify_agent_signature(agent: Agent, payload: dict[str, Any], signature: str) -> None:
    try:
        sig = base64.b64decode(signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"signature is not base64: {e}") from e
    try:
        verify_key = extract_verify_key_from_did_document(agent.did_document or {})
        verify_key.verify(canonical_json_bytes(payload), sig)
    except SponsorshipInvalid as e:
        raise HTTPException(status_code=400, detail=f"agent DID has no usable Ed25519 key: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bid signature invalid: {e}") from e


async def _load_request_or_404(session: AsyncSession, request_id: uuid.UUID):
    row = await rfq_repo.get_request(session, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"request {request_id} not found")
    return row


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create an RFQ service request")
@limiter.limit("30/minute")
async def create_request(
    request: Request,
    body: CreateRequestBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_usdc(body.currency)
    buyer = await _load_agent_or_404(session, body.buyer_did)
    row = await rfq_repo.create_request(
        session,
        buyer_did=buyer.did,
        title=body.title,
        description=body.description,
        capability=body.capability,
        constraints=body.constraints,
        max_price_micro_usdc=body.max_price_micro_usdc,
        currency=body.currency,
        deadline=body.deadline,
    )
    await session.commit()
    return rfq_repo.request_to_public_dict(row)


@router.get("", summary="List open RFQ service requests")
async def list_requests(
    status_filter: str | None = "open",
    capability: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be in 1..200")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    parsed_status = None
    if status_filter is not None:
        try:
            parsed_status = ServiceRequestStatus(status_filter)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid status: {e}") from e
    rows = await rfq_repo.list_requests(
        session,
        status=parsed_status,
        capability=capability,
        limit=limit,
        offset=offset,
    )
    return {
        "total": len(rows),
        "requests": [
            rfq_repo.request_to_public_dict(
                row, bid_count=await rfq_repo.count_bids_for_request(session, row.id)
            )
            for row in rows
        ],
    }


@router.get("/{request_id}", summary="Get an RFQ request with bids")
async def get_request(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _load_request_or_404(session, _parse_request_id(request_id))
    bids = await rfq_repo.list_bids_for_request(session, row.id)
    body = rfq_repo.request_to_public_dict(row, bid_count=len(bids))
    body["bids"] = [rfq_repo.bid_to_public_dict(bid) for bid in bids]
    return body


@router.post("/{request_id}/bids", status_code=status.HTTP_201_CREATED, summary="Submit a signed bid")
@limiter.limit("60/minute")
async def create_bid(
    request: Request,
    request_id: str,
    body: CreateBidBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rid = _parse_request_id(request_id)
    req = await _load_request_or_404(session, rid)
    if req.status != ServiceRequestStatus.open:
        raise HTTPException(status_code=409, detail=f"request is {req.status.value}")
    _require_usdc(body.currency)
    if body.price_micro_usdc > req.max_price_micro_usdc:
        raise HTTPException(status_code=400, detail="bid exceeds request max_price_micro_usdc")
    provider = await _load_agent_or_404(session, body.provider_did)
    if provider.did == req.buyer_did:
        raise HTTPException(status_code=400, detail="provider cannot bid on its own request")
    if await rfq_repo.count_bids_for_request(session, rid) >= MAX_BIDS_PER_REQUEST:
        raise HTTPException(status_code=429, detail="request bid limit reached")
    provider_bid_count = await rfq_repo.count_bids_for_provider(
        session, request_id=rid, provider_did=provider.did
    )
    if provider_bid_count >= MAX_BIDS_PER_AGENT_PER_REQUEST:
        raise HTTPException(status_code=429, detail="provider bid limit reached for this request")
    if await rfq_repo.nonce_exists(session, request_id=rid, provider_did=provider.did, nonce=body.nonce):
        raise HTTPException(status_code=409, detail="nonce already used for this request/provider")
    _require_payload_matches(
        payload=body.signed_payload,
        request_id=rid,
        provider_did=provider.did,
        price_micro_usdc=body.price_micro_usdc,
        currency=body.currency,
        nonce=body.nonce,
        expires_at=body.expires_at,
    )
    _verify_agent_signature(provider, body.signed_payload, body.signature)
    row = await rfq_repo.create_bid(
        session,
        request_id=rid,
        provider_did=provider.did,
        price_micro_usdc=body.price_micro_usdc,
        currency=body.currency,
        message=body.message,
        signed_payload=body.signed_payload,
        signature=body.signature,
        nonce=body.nonce,
        bid_hash=bid_hash(body.signed_payload),
        expires_at=body.expires_at,
    )
    buyer = await agents_repo.get_by_did(session, req.buyer_did)
    if buyer is not None:
        await enqueue_for_agent(
            session,
            agent=buyer,
            job_id=None,
            event_type="bid.created",
            payload={"request_id": str(req.id), "bid_id": str(row.id), "bid_hash": row.bid_hash},
        )
    await session.commit()
    return rfq_repo.bid_to_public_dict(row)


@router.post("/{request_id}/bids/{bid_id}/accept", summary="Accept a bid")
async def accept_bid(
    request_id: str,
    bid_id: str,
    body: AcceptBidBody,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rid = _parse_request_id(request_id)
    req = await _load_request_or_404(session, rid)
    if req.buyer_did != body.buyer_did:
        raise HTTPException(status_code=403, detail="only the request buyer can accept a bid")
    if req.status != ServiceRequestStatus.open:
        raise HTTPException(status_code=409, detail=f"request is {req.status.value}")
    bid = await rfq_repo.get_bid(session, _parse_bid_id(bid_id))
    if bid is None or bid.request_id != rid:
        raise HTTPException(status_code=404, detail=f"bid {bid_id} not found for request")
    if body.bid_hash is not None and body.bid_hash != bid.bid_hash:
        raise HTTPException(status_code=400, detail="bid_hash does not match accepted bid")
    await rfq_repo.accept_bid(session, request=req, bid=bid)
    provider = await agents_repo.get_by_did(session, bid.provider_did)
    if provider is not None:
        await enqueue_for_agent(
            session,
            agent=provider,
            job_id=None,
            event_type="bid.accepted",
            payload={"request_id": str(req.id), "bid_id": str(bid.id), "bid_hash": bid.bid_hash},
        )
    await session.commit()
    return {"request": rfq_repo.request_to_public_dict(req), "bid": rfq_repo.bid_to_public_dict(bid)}
