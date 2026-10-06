"""Generate the synthetic billing database.

    python -m finance_ops.data.generate [--out data/finance_ops.sqlite] [--seed 7]

The same seed always produces the same database: every random choice comes
from one seeded Random, consumed in a fixed order.
"""

import argparse
import random
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

from finance_ops.config import db_path
from finance_ops.data import scenario as sc
from finance_ops.rules import overage_charge_minor, round_minor

WEEKDAY_FACTOR = 1.15
WEEKEND_FACTOR = 0.62
DAYS_PER_MONTH = 30.4
ACCOUNT_NUMBERS = range(1001, 1041)
USAGE_START = sc.FIRST_BILLED_MONTH


@dataclass(frozen=True)
class Invoice:
    invoice_id: str
    account_id: str
    period_start: date
    period_end: date
    issued_on: date
    due_on: date
    currency: str
    plan_id_billed: str
    platform_fee_minor: int
    credits_billed: int
    allowance_applied: int
    overage_rate_applied_minor_per_1k: int
    usage_charge_minor: int

    @property
    def total_minor(self) -> int:
        return self.platform_fee_minor + self.usage_charge_minor


def month_end(day: date) -> date:
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def billed_months() -> list[date]:
    months, current = [], sc.FIRST_BILLED_MONTH
    while current <= sc.LAST_BILLED_MONTH:
        months.append(current)
        current = month_end(current) + timedelta(days=1)
    return months


def build_accounts(rng: random.Random) -> list[sc.AccountSpec]:
    first_parts = list(sc.NAME_FIRST_PARTS)
    rng.shuffle(first_parts)
    unused_names = iter(first_parts)
    specs = []
    for number in ACCOUNT_NUMBERS:
        account_id = f"ACC-{number}"
        planted = sc.PLANTED_ACCOUNTS.get(account_id)
        specs.append(planted or random_account(account_id, next(unused_names), rng))
    return specs


def random_account(account_id: str, first_part: str, rng: random.Random) -> sc.AccountSpec:
    country = rng.choice(sorted(sc.COUNTRY_CURRENCY))
    name = f"{first_part} {rng.choice(sc.NAME_SECOND_PARTS)} {sc.LEGAL_SUFFIX[country]}"
    plan_id = rng.choices(["STARTER", "GROWTH", "SCALE", "ENTERPRISE"], weights=[4, 4, 2, 1])[0]
    created_on = sc.LATE_STARTERS.get(account_id) or date(2025, rng.randint(1, 12), 1)
    return sc.AccountSpec(
        account_id=account_id,
        name=name,
        country=country,
        plan_history=((plan_id, created_on),),
        utilisation=round(rng.uniform(0.4, 1.3), 2),
        created_on=created_on,
        monthly_growth=round(rng.uniform(-0.02, 0.05), 3),
        notes=rng.choice(sc.BENIGN_NOTES),
    )


def plan_on(spec: sc.AccountSpec, day: date) -> str | None:
    """The plan in effect on a given day, or None before the first subscription."""
    current = None
    for plan_id, start in spec.plan_history:
        if start <= day:
            current = plan_id
    return current


def utilisation_for(spec: sc.AccountSpec, day: date) -> float:
    explicit = dict(spec.utilisation_by_month)
    key = day.strftime("%Y-%m")
    if key in explicit:
        return explicit[key]
    months_since_start = (day.year - USAGE_START.year) * 12 + day.month - USAGE_START.month
    return spec.utilisation * (1 + spec.monthly_growth) ** months_since_start


def generate_usage(specs: list[sc.AccountSpec], rng: random.Random) -> dict[str, dict[date, int]]:
    """Daily metered credits per account, from April to the day the usage feed stopped."""
    feed_through = sc.FEEDS["usage"][0]
    usage: dict[str, dict[date, int]] = {}
    for spec in specs:
        base = sc.PLANS[spec.plan_history[0][0]].included_credits
        gap = sc.MISSING_USAGE.get(spec.account_id)
        days: dict[date, int] = {}
        day = max(USAGE_START, spec.plan_history[0][1])
        while day <= feed_through:
            factor = WEEKDAY_FACTOR if day.weekday() < 5 else WEEKEND_FACTOR
            mean = base * utilisation_for(spec, day) / DAYS_PER_MONTH
            credits = round(mean * factor * rng.uniform(0.9, 1.1))
            if not (gap and gap[0] <= day <= gap[1]):
                days[day] = credits
            day += timedelta(days=1)
        usage[spec.account_id] = days
    return usage


def build_invoices(specs: list[sc.AccountSpec], usage: dict[str, dict[date, int]]) -> list[Invoice]:
    invoices = []
    for spec in specs:
        currency = sc.COUNTRY_CURRENCY[spec.country]
        for start in billed_months():
            plan_id = plan_on(spec, start)
            if plan_id is None:
                continue
            end = month_end(start)
            invoice_id = f"INV-{start:%Y%m}-{spec.account_id[-4:]}"
            billed_plan = sc.PLANS[plan_id]
            rating_plan = sc.PLANS[sc.MISRATED_INVOICES.get(invoice_id, plan_id)]
            credits = sum(v for d, v in usage[spec.account_id].items() if start <= d <= end)
            issued = end + timedelta(days=1)
            invoices.append(
                Invoice(
                    invoice_id=invoice_id,
                    account_id=spec.account_id,
                    period_start=start,
                    period_end=end,
                    issued_on=issued,
                    due_on=issued + timedelta(days=sc.PAYMENT_TERMS_DAYS),
                    currency=currency,
                    plan_id_billed=plan_id,
                    platform_fee_minor=billed_plan.monthly_fee_minor,
                    credits_billed=credits,
                    allowance_applied=rating_plan.included_credits,
                    overage_rate_applied_minor_per_1k=rating_plan.overage_rate_minor_per_1k,
                    usage_charge_minor=overage_charge_minor(
                        credits,
                        rating_plan.included_credits,
                        rating_plan.overage_rate_minor_per_1k,
                    ),
                )
            )
    return invoices


def build_settlements(
    invoices: list[Invoice], rng: random.Random
) -> tuple[list[tuple], list[tuple]]:
    """Payments and credit notes. Unplanted invoices are paid within terms if due by now."""
    payments_through = sc.FEEDS["payments"][0]
    payments, credit_notes = [], []
    for invoice in sorted(invoices, key=lambda i: i.invoice_id):
        days_to_pay = rng.randint(2, 27)  # drawn for every invoice to keep the stream stable
        amount = invoice.total_minor
        paid_on = invoice.issued_on + timedelta(days=days_to_pay)
        if invoice.invoice_id in sc.UNPAID_INVOICES:
            continue
        if invoice.invoice_id in sc.CREDIT_NOTES:
            share, reason, issued_on = sc.CREDIT_NOTES[invoice.invoice_id]
            credit = round_minor(invoice.platform_fee_minor * share)
            credit_notes.append(
                (
                    f"CN-{len(credit_notes) + 1:04d}",
                    invoice.invoice_id,
                    issued_on.isoformat(),
                    credit,
                    reason,
                )
            )
            amount -= credit
        if invoice.invoice_id in sc.PARTLY_PAID_INVOICES:
            amount = round_minor(amount * sc.PARTLY_PAID_INVOICES[invoice.invoice_id])
            paid_on = invoice.due_on - timedelta(days=10)
        if paid_on <= payments_through:
            payments.append(
                (f"PAY-{len(payments) + 1:06d}", invoice.invoice_id, paid_on.isoformat(), amount)
            )
    return payments, credit_notes


def meta_rows(seed: int) -> list[tuple[str, str]]:
    return [
        ("synthetic", "true"),
        (
            "notice",
            "Synthetic data generated by finance_ops.data.generate. "
            "No real customers, invoices or payments.",
        ),
        ("seed", str(seed)),
        ("snapshot_date", sc.SNAPSHOT_DATE.isoformat()),
        ("snapshot_time", sc.SNAPSHOT_TIME),
        ("reporting_currency", sc.REPORTING_CURRENCY),
        ("payment_terms_days", str(sc.PAYMENT_TERMS_DAYS)),
    ]


def subscription_rows(specs: list[sc.AccountSpec]) -> list[tuple]:
    rows = []
    for spec in specs:
        history = spec.plan_history
        for index, (plan_id, start) in enumerate(history):
            is_last = index == len(history) - 1
            end = None if is_last else (history[index + 1][1] - timedelta(days=1)).isoformat()
            rows.append(
                (
                    f"SUB-{spec.account_id[-4:]}-{index + 1}",
                    spec.account_id,
                    plan_id,
                    start.isoformat(),
                    end,
                )
            )
    return rows


def account_rows(specs: list[sc.AccountSpec], rng: random.Random) -> list[tuple]:
    return [
        (
            spec.account_id,
            spec.name,
            spec.country,
            sc.COUNTRY_CURRENCY[spec.country],
            sc.SEGMENT_BY_PLAN[spec.plan_history[-1][0]],
            f"AM-{rng.randint(1, 6):02d}",
            spec.created_on.isoformat(),
            spec.notes,
        )
        for spec in specs
    ]


def invoice_row(invoice: Invoice) -> tuple:
    return (
        invoice.invoice_id,
        invoice.account_id,
        invoice.period_start.isoformat(),
        invoice.period_end.isoformat(),
        invoice.issued_on.isoformat(),
        invoice.due_on.isoformat(),
        invoice.currency,
        invoice.plan_id_billed,
        invoice.platform_fee_minor,
        invoice.credits_billed,
        invoice.allowance_applied,
        invoice.overage_rate_applied_minor_per_1k,
        invoice.usage_charge_minor,
        invoice.total_minor,
    )


def build_tables(seed: int) -> dict[str, list[tuple]]:
    """Every table's rows, in insertion order. All randomness happens here."""
    rng = random.Random(seed)
    specs = build_accounts(rng)
    accounts = account_rows(specs, rng)
    usage = generate_usage(specs, rng)
    invoices = build_invoices(specs, usage)
    payments, credit_notes = build_settlements(invoices, rng)
    return {
        "meta": meta_rows(seed),
        "plans": [
            (
                p.plan_id,
                p.name,
                p.monthly_fee_minor,
                p.included_credits,
                p.overage_rate_minor_per_1k,
            )
            for p in sc.PLANS.values()
        ],
        "accounts": accounts,
        "subscriptions": subscription_rows(specs),
        "usage_daily": [
            (account_id, day.isoformat(), credits)
            for account_id, days in usage.items()
            for day, credits in days.items()
        ],
        "invoices": [invoice_row(invoice) for invoice in invoices],
        "payments": payments,
        "credit_notes": credit_notes,
        "fx_rates": [
            (currency, str(rate), sc.FX_RATE_DATE.isoformat())
            for currency, rate in sc.FX_TO_REPORTING.items()
        ],
        "feed_status": [
            (feed, covers.isoformat(), expected.isoformat(), loaded)
            for feed, (covers, expected, loaded) in sc.FEEDS.items()
        ],
    }


def write_database(path: Path, seed: int = sc.DEFAULT_SEED) -> dict[str, int]:
    """Build the database at `path`, replacing any existing file. Returns row counts."""
    tables = build_tables(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    schema = files("finance_ops.data").joinpath("schema.sql").read_text()
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(schema)
        for table, rows in tables.items():
            if rows:
                placeholders = ", ".join("?" * len(rows[0]))
                # Table names come from the dict above, never from input.
                conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    return {table: len(rows) for table, rows in tables.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic billing database.")
    parser.add_argument("--out", type=Path, default=db_path(), help="output SQLite file")
    parser.add_argument("--seed", type=int, default=sc.DEFAULT_SEED)
    args = parser.parse_args()
    counts = write_database(args.out, args.seed)
    print(f"Wrote {args.out} (seed {args.seed}, synthetic data)")
    for table, count in counts.items():
        print(f"  {table:<14} {count:>6}")


if __name__ == "__main__":
    main()
