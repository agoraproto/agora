"""Payment / quote routes (Spec section 6.5, ADR 004)."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..pricing import compute_fee, is_amount_too_small

router = APIRouter()


class QuoteRequest(BaseModel):
    amount: str
    currency: str = "EURC"


class QuoteResponse(BaseModel):
    amount: str
    currency: str
    fee: str
    platform_cut: str
    insurance_cut: str
    payee_receives: str
    effective_pct: str


@router.post("/quote", response_model=QuoteResponse)
async def quote(payload: QuoteRequest) -> QuoteResponse:
    try:
        amount = Decimal(payload.amount)
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"invalid amount: {e}") from e
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    if is_amount_too_small(amount):
        raise HTTPException(status_code=400, detail="amount too small (min fee would consume payout)")
    b = compute_fee(amount)
    return QuoteResponse(
        amount=str(b.amount),
        currency=payload.currency,
        fee=str(b.fee),
        platform_cut=str(b.platform_cut),
        insurance_cut=str(b.insurance_cut),
        payee_receives=str(b.payee_receives),
        effective_pct=str(b.effective_pct),
    )


@router.post("/execute")
async def execute(payload: dict) -> dict:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Bootstrap phase: off-chain ledger first (ADR 003).")


@router.get("/{tx_id}")
async def get_tx(tx_id: str) -> dict:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not yet implemented.")
