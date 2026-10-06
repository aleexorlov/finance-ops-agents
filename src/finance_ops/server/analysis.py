"""Checks the tools run on the data: usage coverage and invoice reconciliation."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from finance_ops.rules import (
    BUCKET_ORDER,
    ageing_bucket,
    money,
    overage_charge_minor,
    rate_per_1k,
    to_reporting_minor,
)
from finance_ops.server.envelope import Status


@dataclass(frozen=True)
class Coverage:
    """Which expected days of usage are present, and why any are missing."""

    expected_days: tuple[date, ...]
    recorded_days: tuple[date, ...]
    gap_days: tuple[date, ...]  # missing although the feed should have them
    behind_days: tuple[date, ...]  # missing because the feed has not caught up

    @property
    def complete(self) -> bool:
        return not self.gap_days and not self.behind_days

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_expected_day": _iso(self.expected_days[0] if self.expected_days else None),
            "last_expected_day": _iso(self.expected_days[-1] if self.expected_days else None),
            "data_through": _iso(max(self.recorded_days) if self.recorded_days else None),
            "days_expected": len(self.expected_days),
            "days_with_data": len(self.recorded_days),
            "days_missing": len(self.gap_days) + len(self.behind_days),
            "missing_dates": [d.isoformat() for d in (*self.gap_days, *self.behind_days)],
        }


def coverage(expected_days: list[date], daily: dict[date, int], covers_through: date) -> Coverage:
    missing = [d for d in expected_days if d not in daily]
    return Coverage(
        expected_days=tuple(expected_days),
        recorded_days=tuple(d for d in expected_days if d in daily),
        gap_days=tuple(d for d in missing if d <= covers_through),
        behind_days=tuple(d for d in missing if d > covers_through),
    )


def gap_message(cov: Coverage) -> str:
    days = ", ".join(d.isoformat() for d in cov.gap_days)
    return (
        f"No usage was recorded on {len(cov.gap_days)} day(s) that should have data: {days}. "
        "Totals cover only the days with data. Treat the shortfall as missing data, not as "
        "lower usage; it cannot be estimated from this data."
    )


def behind_message(covers_through: date, expected_through: date) -> str:
    return (
        f"The usage feed has data only through {covers_through.isoformat()} but should be "
        f"complete through {expected_through.isoformat()}. Totals stop at "
        f"{covers_through.isoformat()} and are incomplete."
    )


def usage_status(
    cov: Coverage, covers_through: date, expected_through: date
) -> tuple[Status, str | None]:
    """Status and message for a usage window: stale beats partial beats ok."""
    messages = [gap_message(cov)] if cov.gap_days else []
    if cov.behind_days:
        messages.append(behind_message(covers_through, expected_through))
    status: Status = "stale" if cov.behind_days else "partial" if cov.gap_days else "ok"
    return status, " ".join(messages) or None


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def reconcile(
    position: sqlite3.Row, plan: sqlite3.Row, metered_credits: int
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], int]:
    """Recompute an invoice from metered usage and the plan in effect.

    Returns (billed, expected, differences, billed_minus_expected_minor).
    """
    expected_usage = overage_charge_minor(
        metered_credits, plan["included_credits"], plan["overage_rate_minor_per_1k"]
    )
    expected_total = plan["monthly_fee_minor"] + expected_usage
    checks = [
        ("plan", position["plan_id_billed"], plan["plan_id"]),
        ("platform_fee", money(position["platform_fee_minor"]), money(plan["monthly_fee_minor"])),
        ("credits", position["credits_billed"], metered_credits),
        ("allowance_credits", position["allowance_applied"], plan["included_credits"]),
        (
            "overage_rate_per_1k_credits",
            rate_per_1k(position["overage_rate_applied_minor_per_1k"]),
            rate_per_1k(plan["overage_rate_minor_per_1k"]),
        ),
        ("usage_charge", money(position["usage_charge_minor"]), money(expected_usage)),
        ("total", money(position["total_minor"]), money(expected_total)),
    ]
    billed = {name: billed_value for name, billed_value, _ in checks}
    expected = {name: expected_value for name, _, expected_value in checks}
    differences = [{"field": name, "billed": b, "expected": e} for name, b, e in checks if b != e]
    return billed, expected, differences, position["total_minor"] - expected_total


def overdue_report(
    positions: list[sqlite3.Row], rates: dict[str, sqlite3.Row], reporting: str
) -> dict[str, Any]:
    """Overdue invoices with balances converted to the reporting currency, and totals.

    The total in the reporting currency is the sum of the per-invoice conversions,
    so the figures shown always add up.
    """
    invoices, by_currency, by_bucket = [], {}, {}
    for p in positions:
        rate = Decimal(rates[p["currency"]]["rate_to_reporting"])
        converted = to_reporting_minor(p["balance_minor"], rate)
        bucket = ageing_bucket(p["days_past_due"])
        invoices.append(
            {
                "invoice_id": p["invoice_id"],
                "account_id": p["account_id"],
                "account_name": p["account_name"],
                "currency": p["currency"],
                "balance": money(p["balance_minor"]),
                f"balance_in_{reporting.lower()}": money(converted),
                "due_on": p["due_on"],
                "days_overdue": p["days_past_due"],
                "ageing_bucket": bucket,
            }
        )
        count, total = by_currency.get(p["currency"], (0, 0))
        by_currency[p["currency"]] = (count + 1, total + p["balance_minor"])
        count, total = by_bucket.get(bucket, (0, 0))
        by_bucket[bucket] = (count + 1, total + converted)
    return {
        "invoice_count": len(invoices),
        "invoices": invoices,
        "totals_by_currency": [
            {"currency": c, "invoices": n, "balance": money(t)}
            for c, (n, t) in sorted(by_currency.items())
        ],
        "total_in_reporting_currency": {
            "currency": reporting,
            "amount": money(sum(t for _, t in by_bucket.values())),
            "fx_rate_date": rates[reporting]["rate_date"],
            "rates_used": {
                c: rates[c]["rate_to_reporting"] for c in sorted(by_currency) if c != reporting
            },
        },
        "totals_by_ageing_bucket": [
            {"bucket": b, "invoices": n, f"amount_in_{reporting.lower()}": money(t)}
            for b, (n, t) in sorted(by_bucket.items(), key=lambda kv: BUCKET_ORDER.index(kv[0]))
        ],
    }
