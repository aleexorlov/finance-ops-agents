"""Billing arithmetic. Plain code, because these numbers have a right answer.

Used by the data generator to bill, and by the tool server to recompute and
explain. The model never does any of this itself.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

AGEING_BUCKETS = ((30, "1-30 days"), (60, "31-60 days"), (90, "61-90 days"))
OLDEST_BUCKET = "over 90 days"
# Overage is priced per this many credits. Tools return it as a value, so an answer
# saying "0.80 per 1,000 credits" is quoting the tools, not inventing a number.
OVERAGE_UNIT_CREDITS = 1000
BUCKET_ORDER = (*(label for _, label in AGEING_BUCKETS), OLDEST_BUCKET)


def round_minor(value: Decimal) -> int:
    """Round to a whole minor unit (penny or cent), half up."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def overage_charge_minor(credits: int, included_credits: int, rate_minor_per_1k: int) -> int:
    """Charge for credits above the allowance, in minor units."""
    excess = max(0, credits - included_credits)
    return round_minor(Decimal(excess) * rate_minor_per_1k / OVERAGE_UNIT_CREDITS)


def to_reporting_minor(amount_minor: int, rate: Decimal) -> int:
    """Convert an amount in minor units at `rate` (reporting currency per unit)."""
    return round_minor(amount_minor * rate)


def money(minor: int) -> str:
    """Minor units as a decimal string with two places, e.g. 135531 -> '1355.31'."""
    return f"{Decimal(minor) / 100:.2f}"


def rate_per_1k(minor_per_1k: int) -> str:
    """Overage rate in major units per 1,000 credits, e.g. 50 -> '0.50'."""
    return f"{Decimal(minor_per_1k) / 100:.2f}"


def pct_change(old: int, new: int) -> float | None:
    """Percentage change from old to new, one decimal place; None when old is zero."""
    if old == 0:
        return None
    change = (Decimal(new) - Decimal(old)) / Decimal(old) * 100
    return float(change.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ageing_bucket(days_overdue: int) -> str:
    for limit, label in AGEING_BUCKETS:
        if days_overdue <= limit:
            return label
    return OLDEST_BUCKET


def days_between(first: date, last: date) -> list[date]:
    """Every date from first to last inclusive (empty if last < first)."""
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]
