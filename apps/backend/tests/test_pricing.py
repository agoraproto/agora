"""Tests for fee computation (ADR 004)."""

from decimal import Decimal

import pytest

from agora_api.pricing import compute_fee, is_amount_too_small


def test_min_fee_applies_at_10eur() -> None:
    # 10 € * 1% = 0.10 €, below 0.50 € floor → floor applies
    b = compute_fee(Decimal("10"))
    assert b.fee == Decimal("0.50")
    assert b.payee_receives == Decimal("9.50")
    assert b.platform_cut == Decimal("0.45")
    assert b.insurance_cut == Decimal("0.05")


def test_one_percent_applies_at_100eur() -> None:
    b = compute_fee(Decimal("100"))
    assert b.fee == Decimal("1.00")
    assert b.payee_receives == Decimal("99.00")
    assert b.platform_cut == Decimal("0.90")
    assert b.insurance_cut == Decimal("0.10")


def test_one_percent_applies_at_1000eur() -> None:
    b = compute_fee(Decimal("1000"))
    assert b.fee == Decimal("10.00")
    assert b.payee_receives == Decimal("990.00")


def test_max_cap_at_10000eur() -> None:
    # 10 000 € * 1% = 100 € → capped at 25 €
    b = compute_fee(Decimal("10000"))
    assert b.fee == Decimal("25.00")
    assert b.payee_receives == Decimal("9975.00")
    assert b.platform_cut == Decimal("22.50")
    assert b.insurance_cut == Decimal("2.50")


def test_max_cap_huge_amount() -> None:
    b = compute_fee(Decimal("100000"))
    assert b.fee == Decimal("25.00")


def test_negative_amount_rejected() -> None:
    with pytest.raises(ValueError):
        compute_fee(Decimal("-1"))


def test_zero_amount_rejected() -> None:
    with pytest.raises(ValueError):
        compute_fee(Decimal("0"))


def test_is_amount_too_small() -> None:
    assert is_amount_too_small(Decimal("0.50")) is True
    assert is_amount_too_small(Decimal("0.49")) is True
    assert is_amount_too_small(Decimal("0.51")) is False
