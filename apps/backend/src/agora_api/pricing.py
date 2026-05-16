"""Fee computation per ADR 004.

Formula: max(min_fee, min(max_fee, fee_bps * amount))

Insurance pool gets `insurance_share_bps` of the fee; the platform gets the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .config import get_settings

# All amounts in this module are Decimals representing fiat units (e.g. EUR or
# stablecoin major units). For onchain conversion we scale by 1e6 for USDC.
_TWO_PLACES = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeBreakdown:
    """Result of fee computation for an order amount."""

    amount: Decimal           # original order amount
    fee: Decimal              # total fee charged
    platform_cut: Decimal     # share to platform
    insurance_cut: Decimal    # share to insurance pool
    payee_receives: Decimal   # amount - fee
    effective_pct: Decimal    # fee / amount * 100 (for reporting)

    def to_dict(self) -> dict[str, str]:
        return {
            "amount": str(self.amount),
            "fee": str(self.fee),
            "platform_cut": str(self.platform_cut),
            "insurance_cut": str(self.insurance_cut),
            "payee_receives": str(self.payee_receives),
            "effective_pct": str(self.effective_pct),
        }


def compute_fee(amount: Decimal) -> FeeBreakdown:
    """Compute the platform fee for a given order amount (in fiat major units).

    Examples:
        >>> compute_fee(Decimal("10")).fee
        Decimal('0.50')
        >>> compute_fee(Decimal("100")).fee
        Decimal('1.00')
        >>> compute_fee(Decimal("10000")).fee
        Decimal('25.00')
    """
    s = get_settings()
    if amount <= 0:
        raise ValueError("amount must be > 0")

    raw = amount * Decimal(s.fee_bps) / Decimal(10_000)
    raw = _round_money(raw)

    if raw < s.fee_min_eur:
        fee = s.fee_min_eur
    elif raw > s.fee_max_eur:
        fee = s.fee_max_eur
    else:
        fee = raw

    insurance_cut = _round_money(fee * Decimal(s.insurance_share_bps) / Decimal(10_000))
    platform_cut = _round_money(fee - insurance_cut)
    payee = _round_money(amount - fee)

    pct = (fee / amount * Decimal(100)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    return FeeBreakdown(
        amount=_round_money(amount),
        fee=fee,
        platform_cut=platform_cut,
        insurance_cut=insurance_cut,
        payee_receives=payee,
        effective_pct=pct,
    )


def is_amount_too_small(amount: Decimal) -> bool:
    """Bootstrap-rule: don't accept jobs whose total ≤ min fee (would be 100%+ fee)."""
    s = get_settings()
    return amount <= s.fee_min_eur
