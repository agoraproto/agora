"""Off-chain ledger (ADR 003) - double-entry style with append-only audit log.

Every balance change is recorded as a LedgerEntry; LedgerBalance is a
materialized projection of those entries. The escrow flow:

  Job created   -> requester.available -= amount,  requester.in_escrow += amount
  Job approved  -> requester.in_escrow -= amount
                   payee.available += payout
                   platform.available += platform_fee
                   insurance.available += insurance_fee
  Job refunded  -> requester.in_escrow -= amount,  requester.available += amount
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import LedgerBalance, LedgerEntry, LedgerEntryType

# Special pseudo-DIDs for platform/insurance pools. They aren't real agents
# but are addressable in the ledger.
PLATFORM_DID = "did:agora:platform"
INSURANCE_DID = "did:agora:insurance_pool"


async def get_balance(
    session: AsyncSession, agent_did: str, currency: str = "EURC"
) -> LedgerBalance:
    result = await session.execute(
        select(LedgerBalance).where(
            LedgerBalance.agent_did == agent_did,
            LedgerBalance.currency == currency,
        )
    )
    bal = result.scalar_one_or_none()
    if bal is None:
        bal = LedgerBalance(
            agent_did=agent_did,
            currency=currency,
            available=Decimal("0"),
            in_escrow=Decimal("0"),
        )
        session.add(bal)
        await session.flush()
    return bal


async def _record(
    session: AsyncSession,
    *,
    agent_did: str,
    entry_type: LedgerEntryType,
    delta_available: Decimal = Decimal("0"),
    delta_escrow: Decimal = Decimal("0"),
    job_id: uuid.UUID | None = None,
    note: str | None = None,
    currency: str = "EURC",
) -> None:
    bal = await get_balance(session, agent_did, currency)
    bal.available = (bal.available or Decimal("0")) + delta_available
    bal.in_escrow = (bal.in_escrow or Decimal("0")) + delta_escrow
    session.add(
        LedgerEntry(
            agent_did=agent_did,
            currency=currency,
            entry_type=entry_type,
            delta_available=delta_available,
            delta_escrow=delta_escrow,
            job_id=job_id,
            note=note,
        )
    )
    await session.flush()


async def deposit(
    session: AsyncSession, agent_did: str, amount: Decimal, *, note: str = "manual deposit"
) -> None:
    """Credit available balance. In Bootstrap-Phase this is admin-triggered;
    in Onchain-Phase it is reconciled from on-chain transfers.
    """
    if amount <= 0:
        raise ValueError("deposit amount must be > 0")
    await _record(
        session,
        agent_did=agent_did,
        entry_type=LedgerEntryType.deposit,
        delta_available=amount,
        note=note,
    )


async def hold_escrow(
    session: AsyncSession, payer_did: str, amount: Decimal, job_id: uuid.UUID
) -> None:
    """Move amount from payer.available -> payer.in_escrow."""
    if amount <= 0:
        raise ValueError("escrow amount must be > 0")
    bal = await get_balance(session, payer_did)
    if (bal.available or Decimal("0")) < amount:
        raise InsufficientFunds(payer_did, amount, bal.available or Decimal("0"))
    await _record(
        session,
        agent_did=payer_did,
        entry_type=LedgerEntryType.escrow_hold,
        delta_available=-amount,
        delta_escrow=amount,
        job_id=job_id,
        note="job escrow",
    )


async def release_escrow(
    session: AsyncSession,
    *,
    payer_did: str,
    payee_did: str,
    amount: Decimal,
    platform_cut: Decimal,
    insurance_cut: Decimal,
    payout: Decimal,
    job_id: uuid.UUID,
) -> None:
    """Approve -> release escrow with fee split.

    Invariant: amount == platform_cut + insurance_cut + payout.
    """
    if platform_cut + insurance_cut + payout != amount:
        raise ValueError(
            f"escrow split mismatch: {platform_cut} + {insurance_cut} + {payout} != {amount}"
        )

    # Drain payer's escrow (the full amount has already been held).
    await _record(
        session,
        agent_did=payer_did,
        entry_type=LedgerEntryType.escrow_release,
        delta_escrow=-amount,
        job_id=job_id,
        note="job approved",
    )
    if payout > 0:
        await _record(
            session,
            agent_did=payee_did,
            entry_type=LedgerEntryType.escrow_release,
            delta_available=payout,
            job_id=job_id,
            note="job payout",
        )
    if platform_cut > 0:
        await _record(
            session,
            agent_did=PLATFORM_DID,
            entry_type=LedgerEntryType.platform_fee,
            delta_available=platform_cut,
            job_id=job_id,
            note="platform fee",
        )
    if insurance_cut > 0:
        await _record(
            session,
            agent_did=INSURANCE_DID,
            entry_type=LedgerEntryType.insurance_fee,
            delta_available=insurance_cut,
            job_id=job_id,
            note="insurance pool",
        )


async def refund_escrow(
    session: AsyncSession, payer_did: str, amount: Decimal, job_id: uuid.UUID
) -> None:
    """Move amount back from payer.in_escrow -> payer.available."""
    if amount <= 0:
        raise ValueError("refund amount must be > 0")
    await _record(
        session,
        agent_did=payer_did,
        entry_type=LedgerEntryType.refund,
        delta_available=amount,
        delta_escrow=-amount,
        job_id=job_id,
        note="job refunded",
    )


class InsufficientFunds(Exception):
    def __init__(self, did: str, requested: Decimal, available: Decimal) -> None:
        super().__init__(
            f"agent {did} has insufficient funds: requested {requested}, has {available}"
        )
        self.did = did
        self.requested = requested
        self.available = available
