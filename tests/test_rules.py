"""The billing arithmetic. Plain code with right answers, so it gets exact tests."""

from datetime import date
from decimal import Decimal

import pytest

from finance_ops.rules import (
    ageing_bucket,
    days_between,
    money,
    overage_charge_minor,
    pct_change,
    rate_per_1k,
    round_minor,
    to_reporting_minor,
)


@pytest.mark.parametrize(
    ("days", "bucket"),
    [
        (1, "1-30 days"),
        (30, "1-30 days"),
        (31, "31-60 days"),
        (60, "31-60 days"),
        (61, "61-90 days"),
        (90, "61-90 days"),
        (91, "over 90 days"),
        (400, "over 90 days"),
    ],
)
def test_ageing_bucket_boundaries(days: int, bucket: str) -> None:
    assert ageing_bucket(days) == bucket


@pytest.mark.parametrize(
    ("value", "rounded"),
    [("0.5", 1), ("1.5", 2), ("2.5", 3), ("-0.5", -1), ("2.4999", 2)],
)
def test_round_minor_rounds_half_up_not_to_even(value: str, rounded: int) -> None:
    assert round_minor(Decimal(value)) == rounded


def test_no_overage_at_or_below_the_allowance() -> None:
    assert overage_charge_minor(1_000_000, 1_000_000, 50) == 0
    assert overage_charge_minor(10, 1_000_000, 50) == 0


def test_overage_is_charged_per_thousand_credits_and_rounded() -> None:
    # 1,001 credits over at 50 minor units per 1,000 = 50.05 minor units -> 50
    assert overage_charge_minor(1_001_001, 1_000_000, 50) == 50
    # 2,112,612 over at 0.50 per 1,000 = 1056.306 -> 1056.31
    assert overage_charge_minor(3_112_612, 1_000_000, 50) == 105_631


def test_conversion_rounds_each_amount_half_up() -> None:
    assert to_reporting_minor(29_900, Decimal("0.7800")) == 23_322
    assert to_reporting_minor(1, Decimal("0.5")) == 1


@pytest.mark.parametrize(
    ("minor", "text"), [(135531, "1355.31"), (0, "0.00"), (-28105, "-281.05"), (5, "0.05")]
)
def test_money_formats_minor_units(minor: int, text: str) -> None:
    assert money(minor) == text


def test_rate_per_thousand_is_in_major_units() -> None:
    assert rate_per_1k(50) == "0.50"


def test_pct_change_is_none_from_zero_and_signed_otherwise() -> None:
    assert pct_change(0, 100) is None
    assert pct_change(200, 100) == -50.0
    assert pct_change(135531, 263636) == 94.5


def test_days_between_is_inclusive_and_handles_leap_years() -> None:
    assert len(days_between(date(2024, 2, 1), date(2024, 2, 29))) == 29
    assert days_between(date(2026, 9, 30), date(2026, 9, 29)) == []
