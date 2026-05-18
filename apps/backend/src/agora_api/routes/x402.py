"""x402 — HTTP 402 Payment Required for agent-native payments.

Inspired by the Coinbase x402 spec. The flow is:

  1. Agent calls POST /v1/x402/jobs with the job description but no payment.
  2. Server replies 402 with header
       X-Payment-Required: <json>
     describing exactly which on-chain payment is needed (chain, asset,
     contract, amount, recipient, jobId-to-be) plus a short-lived
     payment challenge.
  3. Agent funds the escrow contract on-chain (AgoraEscrow.createJob).
  4. Agent retries the same POST with header
       X-Payment-Tx: <tx_hash>
     pointing at the transaction that fulfilled the challenge.
  5. Server verifies the tx on-chain, mirrors the job in its DB, and
     returns 201 with the job representation.

This endpoint lives next to the off-chain ledger jobs router (/v1/jobs);
both can coexist while we migrate. x402 is the agent-native rail.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..chain import get_escrow_client
from ..config import get_settings
from ..db import agents_repo, jobs_repo
from ..db.base import get_session
from ..db.models import Job, JobStatus
from ..rate_limit import limiter
from ..webhooks.delivery import enqueue_for_agent

router = APIRouter()


class X402JobRequest(BaseModel):
    requester_did: str
    provider_did: str
    task: dict[str, Any] = Field(default_factory=dict)
    budget_usdc: str = Field(..., description="Amount in USDC, decimal (e.g. '5.00')")
    deadline_unix: int = Field(..., description="Unix timestamp for job deadline")


def _task_hash(payload: dict[str, Any]) -> bytes:
    """Canonical task hash for on-chain commitment."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).digest()


@router.post(
    "/jobs",
    status_code=status.HTTP_201_CREATED,
    summary="Create a job — pays via x402 / on-chain USDC escrow",
)
@limiter.limit("30/minute")
async def create_x402_job(
    request: Request,
    body: X402JobRequest,
    session: AsyncSession = Depends(get_session),
    x_payment_tx: str | None = Header(default=None, alias="X-Payment-Tx"),
) -> Any:
    settings = get_settings()
    client = get_escrow_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="on-chain settlement disabled (set enable_onchain_payments=true)",
        )

    requester = await agents_repo.get_by_did(session, body.requester_did)
    provider = await agents_repo.get_by_did(session, body.provider_did)
    if requester is None or provider is None:
        raise HTTPException(status_code=404, detail="requester or provider unknown")
    if provider.payout_wallet is None:
        raise HTTPException(
            status_code=409,
            detail=f"provider {body.provider_did} has no payout_wallet set",
        )

    amount = client.to_smallest_unit(Decimal(body.budget_usdc))
    task_hash = _task_hash(body.task)

    # ── Step 1: no X-Payment-Tx → return 402 with payment instructions ──
    if x_payment_tx is None:
        fee = await client.compute_fee(amount)
        payment_required = {
            "version": "1",
            "chain": settings.chain_name,
            "chain_id": settings.chain_id,
            "asset": {
                "kind": "ERC20",
                "address": settings.usdc_contract_address,
                "symbol": "USDC",
                "decimals": settings.usdc_decimals,
            },
            "amount": str(amount),
            "fee_estimate": str(fee),
            "recipient_contract": settings.escrow_contract_address,
            "function": "createJob",
            "args": {
                "payee": provider.payout_wallet,
                "amount": str(amount),
                "taskHash": "0x" + task_hash.hex(),
                "deadline": body.deadline_unix,
            },
            "retry_header": "X-Payment-Tx",
            "expires_in_seconds": 300,
        }
        return Response(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            headers={"X-Payment-Required": json.dumps(payment_required)},
            content=json.dumps(
                {
                    "error": "payment_required",
                    "detail": (
                        "Call AgoraEscrow.createJob with the parameters in "
                        "X-Payment-Required, then retry this request with "
                        "X-Payment-Tx: <tx_hash>."
                    ),
                }
            ),
            media_type="application/json",
        )

    # ── Step 2: client provided X-Payment-Tx → verify and mirror ──
    receipt = client.w3.eth.get_transaction_receipt(x_payment_tx)
    if receipt is None or receipt.get("status") != 1:
        raise HTTPException(status_code=402, detail="payment tx not found or reverted")

    # Extract on-chain jobId from JobCreated event
    onchain_job_id: int | None = None
    for log_entry in receipt["logs"]:
        try:
            parsed = client.escrow.events.JobCreated().process_log(log_entry)
            onchain_job_id = int(parsed["args"]["jobId"])
            # Cheap sanity check: amount and taskHash must match what we asked.
            if int(parsed["args"]["amount"]) != amount:
                raise HTTPException(status_code=402, detail="amount mismatch")
            if bytes(parsed["args"]["taskHash"]) != task_hash:
                raise HTTPException(status_code=402, detail="taskHash mismatch")
            if parsed["args"]["payee"].lower() != provider.payout_wallet.lower():
                raise HTTPException(status_code=402, detail="payee mismatch")
            break
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001
            continue
    if onchain_job_id is None:
        raise HTTPException(status_code=402, detail="JobCreated event missing")

    # Idempotency: same tx hash → return existing row.
    existing = await jobs_repo.find_by_escrow_tx(session, x_payment_tx)
    if existing is not None:
        return _job_view(existing)

    job = Job(
        id=uuid.uuid4(),
        requester_agent_id=requester.id,
        provider_agent_id=provider.id,
        task_spec=body.task,
        status=JobStatus.offered,
        price_amount=client.from_smallest_unit(amount),
        price_currency="USDC",
        escrow_tx_hash=x_payment_tx,
        onchain_job_id=Decimal(onchain_job_id),
        settlement_mode="onchain",
        chain=settings.chain_name,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await enqueue_for_agent(
        session=session,
        agent_did=provider.did,
        event_type="job.offered",
        payload=_job_view(job),
    )
    return _job_view(job)


def _job_view(j: Job) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "requester_agent_id": str(j.requester_agent_id),
        "provider_agent_id": str(j.provider_agent_id),
        "task_spec": j.task_spec,
        "status": j.status.value if hasattr(j.status, "value") else str(j.status),
        "price_amount": str(j.price_amount),
        "price_currency": j.price_currency,
        "escrow_tx_hash": j.escrow_tx_hash,
        "release_tx_hash": j.release_tx_hash,
        "onchain_job_id": str(j.onchain_job_id) if j.onchain_job_id is not None else None,
        "settlement_mode": j.settlement_mode,
        "chain": j.chain,
    }


class X402QuoteRequest(BaseModel):
    provider_did: str
    task: dict[str, Any] = Field(default_factory=dict)
    budget_usdc: str = Field(..., description="Amount in USDC, decimal (e.g. '5.00')")


@router.post(
    "/quote",
    summary="Get a price quote without committing to a job (no 402, no DB write)",
)
async def quote(
    body: X402QuoteRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Lightweight pricing oracle — agents call this to compare providers."""
    settings = get_settings()
    client = get_escrow_client()
    if client is None:
        raise HTTPException(status_code=503, detail="on-chain settlement disabled")
    provider = await agents_repo.get_by_did(session, body.provider_did)
    if provider is None:
        raise HTTPException(status_code=404, detail="provider unknown")

    amount = client.to_smallest_unit(Decimal(body.budget_usdc))
    fee = await client.compute_fee(amount)
    provider_payout = amount - fee

    return {
        "chain": settings.chain_name,
        "chain_id": settings.chain_id,
        "asset": {
            "kind": "ERC20",
            "address": settings.usdc_contract_address,
            "symbol": "USDC",
            "decimals": settings.usdc_decimals,
        },
        "budget": {
            "smallest_unit": str(amount),
            "human": body.budget_usdc,
        },
        "platform_fee": {
            "smallest_unit": str(fee),
            "human": str(client.from_smallest_unit(fee)),
        },
        "provider_payout": {
            "smallest_unit": str(provider_payout),
            "human": str(client.from_smallest_unit(provider_payout)),
        },
        "escrow_contract": settings.escrow_contract_address,
        "provider": {
            "did": provider.did,
            "name": provider.name,
            "payout_wallet": provider.payout_wallet,
            "trust_level": provider.trust_level.value if hasattr(provider.trust_level, "value") else str(provider.trust_level),
        },
    }
