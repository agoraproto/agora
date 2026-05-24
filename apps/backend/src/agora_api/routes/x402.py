"""x402 — HTTP 402 Payment Required for agent-native payments.

Inspired by the Coinbase x402 spec. The full job lifecycle is:

  hire    → POST /v1/x402/jobs                  (requester)
              first call:  402 + X-Payment-Required (createJob args)
              retry:       201 with mirrored job row, status="offered"

  result  → POST /v1/x402/jobs/{job_id}/result  (provider)
              first call:  402 + X-Payment-Required (submitResult args)
              retry:       200 with updated job row, status="submitted"

  approve → POST /v1/x402/jobs/{job_id}/approve (requester)
              first call:  402 + X-Payment-Required (approveAndPay args)
              retry:       200 with updated job row, status="completed"

  refund  → POST /v1/x402/jobs/{job_id}/refund  (requester, after deadline)
              first call:  402 + X-Payment-Required (refund args)
              retry:       200 with updated job row, status="refunded"

  dispute → POST /v1/x402/jobs/{job_id}/dispute (either party)
              first call:  402 + X-Payment-Required (dispute args)
              retry:       200 with updated job row, status="disputed"

Every "first call" returns a machine-readable 402 telling the agent the
exact on-chain call to make. Every "retry" verifies the tx receipt on
chain, double-checks the event args against what the API itself
instructed, and only then mutates the DB. The API never signs on the
agent's behalf — agents hold their own keys.

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
from ..db import agents_repo, disputes_repo, jobs_repo, listings_repo, reviews_repo
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
    listing_id: str | None = Field(
        default=None,
        description=(
            "Optional marketplace listing this purchase originates from. "
            "When set, the resulting Job is linked back to the Listing so "
            "the delivery endpoint can authorise the buyer to fetch "
            "`digital_content` after on-chain payment."
        ),
    )


def _task_hash(payload: dict[str, Any]) -> bytes:
    """Canonical task hash for on-chain commitment."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).digest()


def _result_hash(payload: dict[str, Any]) -> bytes:
    """Canonical result hash for on-chain commitment.

    Same scheme as `_task_hash` so providers and verifiers agree on the
    canonical form. The contract only stores the bytes32; agents can
    re-hash off-chain to prove integrity.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).digest()


async def _load_onchain_job_or_404(session: AsyncSession, job_id: str) -> Job:
    """Resolve a job UUID from the URL, ensure it is an on-chain job.

    The x402 lifecycle endpoints only operate on jobs that were created
    via `POST /v1/x402/jobs` (settlement_mode='onchain'); attempting to
    drive an off-chain job through this path is a 409.
    """
    try:
        jid = uuid.UUID(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid job id: {e}") from e
    job = await jobs_repo.get(session, jid)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.settlement_mode != "onchain":
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} is not on-chain (settlement_mode={job.settlement_mode})",
        )
    if job.onchain_job_id is None:
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id} is on-chain but has no onchain_job_id (data inconsistency)",
        )
    return job


def _payment_required_response(payment_required: dict[str, Any], hint: str) -> Response:
    """Build the canonical 402 response — header + JSON body."""
    return Response(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        headers={"X-Payment-Required": json.dumps(payment_required)},
        content=json.dumps({"error": "payment_required", "detail": hint}),
        media_type="application/json",
    )


def _find_event(receipt: Any, event_factory: Any) -> dict[str, Any] | None:
    """Scan a tx receipt for an event matching `event_factory()`.

    Returns the parsed log (with .args, .event, .blockNumber, …) or
    None if no log in this receipt matched. Used so each x402 step can
    re-verify the on-chain side-effect it expected.
    """
    for log_entry in receipt["logs"]:
        try:
            return event_factory().process_log(log_entry)
        except Exception:  # log belongs to a different contract/event
            continue
    return None


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

    # ── Resolve payout wallet (Sprint 10d-1) ──
    # When the buy comes from a marketplace listing, the Listing's
    # payout_wallet is authoritative — it's the wallet the seller chose
    # at listing-time, which may differ from their agent's default.
    # Falls back to the provider agent's payout_wallet for direct
    # agent-to-agent x402 calls without a listing.
    payee_wallet: str | None = None
    listing_for_purchase = None
    if body.listing_id:
        try:
            listing_uuid_check = uuid.UUID(body.listing_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid listing_id: {e}") from e
        listing_for_purchase = await listings_repo.get(session, listing_uuid_check)
        if listing_for_purchase is None:
            raise HTTPException(
                status_code=404, detail=f"listing {body.listing_id} not found"
            )
        payee_wallet = listing_for_purchase.payout_wallet
    if payee_wallet is None:
        payee_wallet = provider.payout_wallet
    if payee_wallet is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"provider {body.provider_did} has no payout_wallet set "
                "(neither on the agent nor on a referenced listing)"
            ),
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
                "payee": payee_wallet,
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
            if parsed["args"]["payee"].lower() != payee_wallet.lower():
                raise HTTPException(status_code=402, detail="payee mismatch")
            break
        except HTTPException:
            raise
        except Exception:
            continue
    if onchain_job_id is None:
        raise HTTPException(status_code=402, detail="JobCreated event missing")

    # Idempotency: same tx hash → return existing row.
    existing = await jobs_repo.find_by_escrow_tx(session, x_payment_tx)
    if existing is not None:
        return _job_view(existing)

    # Optional: link back to a marketplace Listing so the delivery
    # endpoint can authorise the buyer to fetch digital_content later.
    listing_uuid: uuid.UUID | None = None
    if body.listing_id:
        try:
            listing_uuid = uuid.UUID(body.listing_id)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"invalid listing_id: {e}"
            ) from e

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
        listing_id=listing_uuid,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await enqueue_for_agent(
        session,
        agent=provider,
        job_id=job.id,
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
        "listing_id": str(j.listing_id) if j.listing_id is not None else None,
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
            "trust_level": (
                provider.trust_level.value
                if hasattr(provider.trust_level, "value")
                else str(provider.trust_level)
            ),
        },
    }


# ─────────────────────────────────────────────────────────────────────
# Provider-side result submission  (PROVIDER -> AgoraEscrow.submitResult)
# ─────────────────────────────────────────────────────────────────────


class X402ResultRequest(BaseModel):
    result: dict[str, Any] = Field(
        default_factory=dict,
        description="Result payload. Hashed canonically and committed on-chain.",
    )


@router.post(
    "/jobs/{job_id}/result",
    summary="Submit result for an on-chain job (provider, via AgoraEscrow.submitResult)",
)
@limiter.limit("60/minute")
async def submit_x402_result(
    request: Request,
    job_id: str,
    body: X402ResultRequest,
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

    job = await _load_onchain_job_or_404(session, job_id)

    # Allow only the on-chain "Funded" stage (DB-mirror: offered) to be
    # transitioned to "Submitted". Idempotent if already submitted.
    if job.status == JobStatus.submitted:
        return _job_view(job)
    if job.status != JobStatus.offered:
        raise HTTPException(
            status_code=409,
            detail=(
                f"job {job_id} cannot submit result from state "
                f"{job.status.value}; expected 'offered'"
            ),
        )

    result_hash = _result_hash(body.result)
    onchain_job_id_int = int(job.onchain_job_id)  # type: ignore[arg-type]

    # ── Step 1: no X-Payment-Tx → return 402 with submitResult args ──
    if x_payment_tx is None:
        payment_required = {
            "version": "1",
            "chain": settings.chain_name,
            "chain_id": settings.chain_id,
            "amount": "0",
            "fee_estimate": "0",
            "recipient_contract": settings.escrow_contract_address,
            "function": "submitResult",
            "args": {
                "jobId": str(onchain_job_id_int),
                "resultHash": "0x" + result_hash.hex(),
            },
            "retry_header": "X-Payment-Tx",
            "expires_in_seconds": 300,
        }
        return _payment_required_response(
            payment_required,
            hint=(
                "Call AgoraEscrow.submitResult with the parameters in "
                "X-Payment-Required, then retry this request with "
                "X-Payment-Tx: <tx_hash>. Only the registered payee can "
                "submit; the contract enforces NotPayee."
            ),
        )

    # ── Step 2: client provided X-Payment-Tx → verify and apply ──
    receipt = client.w3.eth.get_transaction_receipt(x_payment_tx)
    if receipt is None or receipt.get("status") != 1:
        raise HTTPException(status_code=402, detail="payment tx not found or reverted")

    parsed = _find_event(receipt, client.escrow.events.ResultSubmitted)
    if parsed is None:
        raise HTTPException(status_code=402, detail="ResultSubmitted event missing")
    if int(parsed["args"]["jobId"]) != onchain_job_id_int:
        raise HTTPException(status_code=402, detail="jobId mismatch")
    if bytes(parsed["args"]["resultHash"]) != result_hash:
        raise HTTPException(status_code=402, detail="resultHash mismatch")

    # Mirror state into DB.
    await jobs_repo.set_result(session, job, body.result)
    job.status = JobStatus.submitted
    await session.flush()

    # Notify the requester. Look the agent up so we can pass the full
    # Agent object to `enqueue_for_agent` (Sprint 9b bug taught us not to
    # pass bare DIDs).
    requester = await agents_repo.get_by_id(session, job.requester_agent_id)
    if requester is not None:
        await enqueue_for_agent(
            session,
            agent=requester,
            job_id=job.id,
            event_type="job.result_submitted",
            payload={**_job_view(job), "result": body.result},
        )

    await session.commit()
    await session.refresh(job)
    return _job_view(job)


# ─────────────────────────────────────────────────────────────────────
# Requester-side approval & payout  (REQUESTER -> AgoraEscrow.approveAndPay)
# ─────────────────────────────────────────────────────────────────────


class X402ApproveRequest(BaseModel):
    # No body fields required — the action is implicit in the URL. We
    # keep an empty model to leave room for future fields (approver_did
    # signature, idempotency_key, …).
    pass


@router.post(
    "/jobs/{job_id}/approve",
    summary="Approve a submitted on-chain job and release escrow (requester)",
)
@limiter.limit("60/minute")
async def approve_x402_job(
    request: Request,
    job_id: str,
    body: X402ApproveRequest,
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

    job = await _load_onchain_job_or_404(session, job_id)

    if job.status == JobStatus.completed:
        return _job_view(job)
    if job.status != JobStatus.submitted:
        raise HTTPException(
            status_code=409,
            detail=(
                f"job {job_id} cannot be approved from state "
                f"{job.status.value}; expected 'submitted'"
            ),
        )

    onchain_job_id_int = int(job.onchain_job_id)  # type: ignore[arg-type]

    # ── Step 1: no X-Payment-Tx → return 402 with approveAndPay args ──
    if x_payment_tx is None:
        payment_required = {
            "version": "1",
            "chain": settings.chain_name,
            "chain_id": settings.chain_id,
            "amount": "0",
            "fee_estimate": "0",
            "recipient_contract": settings.escrow_contract_address,
            "function": "approveAndPay",
            "args": {"jobId": str(onchain_job_id_int)},
            "retry_header": "X-Payment-Tx",
            "expires_in_seconds": 300,
        }
        return _payment_required_response(
            payment_required,
            hint=(
                "Call AgoraEscrow.approveAndPay with the parameters in "
                "X-Payment-Required, then retry this request with "
                "X-Payment-Tx: <tx_hash>. Only the payer (original "
                "requester) can approve; the contract enforces NotPayer."
            ),
        )

    # ── Step 2: verify and apply ──
    receipt = client.w3.eth.get_transaction_receipt(x_payment_tx)
    if receipt is None or receipt.get("status") != 1:
        raise HTTPException(status_code=402, detail="payment tx not found or reverted")

    parsed = _find_event(receipt, client.escrow.events.JobApproved)
    if parsed is None:
        raise HTTPException(status_code=402, detail="JobApproved event missing")
    if int(parsed["args"]["jobId"]) != onchain_job_id_int:
        raise HTTPException(status_code=402, detail="jobId mismatch")

    # Mirror state into DB.
    job.release_tx_hash = x_payment_tx
    job.status = JobStatus.completed
    await session.flush()

    # Bump reputation counters for both sides (same as off-chain approve).
    requester = await agents_repo.get_by_id(session, job.requester_agent_id)
    provider = await agents_repo.get_by_id(session, job.provider_agent_id)

    if requester is not None:
        await reviews_repo.increment_jobs_completed(session, requester)
    if provider is not None:
        await reviews_repo.increment_jobs_completed(session, provider)

    # If this job was a marketplace purchase, bump the listing's
    # sales_count so the browse UI reflects what's selling.
    if job.listing_id is not None:
        listing = await listings_repo.get(session, job.listing_id)
        if listing is not None:
            await listings_repo.increment_sales(session, listing)

    # Notify provider that funds were released.
    if provider is not None:
        await enqueue_for_agent(
            session,
            agent=provider,
            job_id=job.id,
            event_type="job.completed",
            payload={
                **_job_view(job),
                "fee_smallest_unit": str(parsed["args"]["fee"]),
                "insurance_smallest_unit": str(parsed["args"]["insuranceCut"]),
            },
        )

    await session.commit()
    await session.refresh(job)
    return _job_view(job)


# ─────────────────────────────────────────────────────────────────────
# Refund path  (REQUESTER -> AgoraEscrow.refund, after deadline)
# ─────────────────────────────────────────────────────────────────────


class X402RefundRequest(BaseModel):
    pass


@router.post(
    "/jobs/{job_id}/refund",
    summary="Refund an unfulfilled on-chain job (requester, after deadline)",
)
@limiter.limit("30/minute")
async def refund_x402_job(
    request: Request,
    job_id: str,
    body: X402RefundRequest,
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

    job = await _load_onchain_job_or_404(session, job_id)

    if job.status == JobStatus.refunded:
        return _job_view(job)
    # Refund is only valid in "Funded" state on-chain (= DB 'offered').
    # Once a result has been submitted, the requester must approve or
    # dispute instead.
    if job.status != JobStatus.offered:
        raise HTTPException(
            status_code=409,
            detail=(
                f"job {job_id} cannot be refunded from state "
                f"{job.status.value}; expected 'offered' (= on-chain 'Funded')"
            ),
        )

    onchain_job_id_int = int(job.onchain_job_id)  # type: ignore[arg-type]

    # ── Step 1: 402 with refund() instructions ──
    if x_payment_tx is None:
        payment_required = {
            "version": "1",
            "chain": settings.chain_name,
            "chain_id": settings.chain_id,
            "amount": "0",
            "fee_estimate": "0",
            "recipient_contract": settings.escrow_contract_address,
            "function": "refund",
            "args": {"jobId": str(onchain_job_id_int)},
            "retry_header": "X-Payment-Tx",
            "expires_in_seconds": 300,
            "note": (
                "AgoraEscrow.refund(jobId) is only callable by anyone "
                "once the on-chain deadline has elapsed (block.timestamp "
                "> deadline). Before then, only the contract owner can "
                "refund. If your tx reverts, check the deadline."
            ),
        }
        return _payment_required_response(
            payment_required,
            hint=(
                "Call AgoraEscrow.refund with the parameters in "
                "X-Payment-Required, then retry this request with "
                "X-Payment-Tx: <tx_hash>."
            ),
        )

    # ── Step 2: verify and apply ──
    receipt = client.w3.eth.get_transaction_receipt(x_payment_tx)
    if receipt is None or receipt.get("status") != 1:
        raise HTTPException(status_code=402, detail="payment tx not found or reverted")

    parsed = _find_event(receipt, client.escrow.events.JobRefunded)
    if parsed is None:
        raise HTTPException(status_code=402, detail="JobRefunded event missing")
    if int(parsed["args"]["jobId"]) != onchain_job_id_int:
        raise HTTPException(status_code=402, detail="jobId mismatch")

    job.release_tx_hash = x_payment_tx  # reuse this column for the refund tx
    job.status = JobStatus.refunded
    await session.flush()

    # Notify both sides.
    requester = await agents_repo.get_by_id(session, job.requester_agent_id)
    provider = await agents_repo.get_by_id(session, job.provider_agent_id)
    payload = {**_job_view(job), "reason": "deadline_or_owner_refund"}
    for agent in (requester, provider):
        if agent is not None:
            await enqueue_for_agent(
                session,
                agent=agent,
                job_id=job.id,
                event_type="job.refunded",
                payload=payload,
            )

    await session.commit()
    await session.refresh(job)
    return _job_view(job)


# ─────────────────────────────────────────────────────────────────────
# Dispute path  (EITHER PARTY -> AgoraEscrow.dispute)
# ─────────────────────────────────────────────────────────────────────


class X402DisputeRequest(BaseModel):
    reason: str = Field(..., description="Short human-readable reason for the dispute")
    raised_by_did: str = Field(
        ..., description="DID of the party raising the dispute (must be party to the job)"
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Off-chain evidence stored in the disputes table; not committed on-chain.",
    )


@router.post(
    "/jobs/{job_id}/dispute",
    summary="Open a dispute on an on-chain job (either party)",
)
@limiter.limit("10/minute")
async def dispute_x402_job(
    request: Request,
    job_id: str,
    body: X402DisputeRequest,
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

    job = await _load_onchain_job_or_404(session, job_id)

    # Idempotent: if already disputed, just return.
    if job.status == JobStatus.disputed:
        return _job_view(job)
    # Contract allows dispute in Funded (= DB 'offered') or Submitted.
    if job.status not in (JobStatus.offered, JobStatus.submitted):
        raise HTTPException(
            status_code=409,
            detail=(
                f"job {job_id} cannot be disputed from state "
                f"{job.status.value}; expected 'offered' or 'submitted'"
            ),
        )

    # Verify the raiser is party to this job.
    raiser = await agents_repo.get_by_did(session, body.raised_by_did)
    if raiser is None:
        raise HTTPException(status_code=404, detail=f"raised_by_did {body.raised_by_did} unknown")
    if raiser.id not in (job.requester_agent_id, job.provider_agent_id):
        raise HTTPException(
            status_code=403,
            detail=f"agent {body.raised_by_did} is not a party to job {job_id}",
        )

    onchain_job_id_int = int(job.onchain_job_id)  # type: ignore[arg-type]

    # ── Step 1: 402 with dispute() instructions ──
    if x_payment_tx is None:
        payment_required = {
            "version": "1",
            "chain": settings.chain_name,
            "chain_id": settings.chain_id,
            "amount": "0",
            "fee_estimate": "0",
            "recipient_contract": settings.escrow_contract_address,
            "function": "dispute",
            "args": {
                "jobId": str(onchain_job_id_int),
                "reason": body.reason,
            },
            "retry_header": "X-Payment-Tx",
            "expires_in_seconds": 300,
        }
        return _payment_required_response(
            payment_required,
            hint=(
                "Call AgoraEscrow.dispute with the parameters in "
                "X-Payment-Required, then retry this request with "
                "X-Payment-Tx: <tx_hash>. Only the payer or payee can "
                "dispute; the contract enforces Unauthorized otherwise."
            ),
        )

    # ── Step 2: verify and apply ──
    receipt = client.w3.eth.get_transaction_receipt(x_payment_tx)
    if receipt is None or receipt.get("status") != 1:
        raise HTTPException(status_code=402, detail="payment tx not found or reverted")

    parsed = _find_event(receipt, client.escrow.events.JobDisputed)
    if parsed is None:
        raise HTTPException(status_code=402, detail="JobDisputed event missing")
    if int(parsed["args"]["jobId"]) != onchain_job_id_int:
        raise HTTPException(status_code=402, detail="jobId mismatch")

    # Record the dispute in the disputes table for later resolution.
    dispute = await disputes_repo.open_dispute(
        session,
        job=job,
        raised_by_id=raiser.id,
        reason=body.reason,
        evidence=body.evidence,
    )
    job.status = JobStatus.disputed
    await session.flush()

    # Notify both sides.
    requester = await agents_repo.get_by_id(session, job.requester_agent_id)
    provider = await agents_repo.get_by_id(session, job.provider_agent_id)
    payload = {
        **_job_view(job),
        "reason": body.reason,
        "raised_by": body.raised_by_did,
        "dispute_id": str(dispute.id),
    }
    for agent in (requester, provider):
        if agent is not None:
            await enqueue_for_agent(
                session,
                agent=agent,
                job_id=job.id,
                event_type="job.disputed",
                payload=payload,
            )

    await session.commit()
    await session.refresh(job)
    return _job_view(job)
