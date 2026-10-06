"""SQL for the tools. Every query is parameterised; nothing is built from user text.

Balances and days overdue are computed in SQL against the snapshot date, never
against the wall clock, so the same question gets the same answer every run.
"""

import sqlite3
from datetime import date

# One row per invoice with what has been paid, credited and is still owed.
INVOICE_POSITIONS = """
WITH paid AS (
    SELECT invoice_id, SUM(amount_minor) AS paid_minor FROM payments GROUP BY invoice_id
),
credited AS (
    SELECT invoice_id, SUM(amount_minor) AS credited_minor FROM credit_notes GROUP BY invoice_id
)
SELECT
    i.*,
    a.name AS account_name,
    p.name AS plan_name_billed,
    COALESCE(paid.paid_minor, 0) AS paid_minor,
    COALESCE(credited.credited_minor, 0) AS credited_minor,
    i.total_minor - COALESCE(paid.paid_minor, 0) - COALESCE(credited.credited_minor, 0)
        AS balance_minor,
    CAST(julianday(:snapshot_date) - julianday(i.due_on) AS INTEGER) AS days_past_due
FROM invoices AS i
JOIN accounts AS a ON a.account_id = i.account_id
JOIN plans AS p ON p.plan_id = i.plan_id_billed
LEFT JOIN paid ON paid.invoice_id = i.invoice_id
LEFT JOIN credited ON credited.invoice_id = i.invoice_id
"""


def account(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()


def account_names(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT account_id, name, country, currency, segment FROM accounts ORDER BY account_id"
    ).fetchall()


def plan_history(conn: sqlite3.Connection, account_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT s.plan_id, p.name, s.start_date, s.end_date, p.monthly_fee_minor,
               p.included_credits, p.overage_rate_minor_per_1k
        FROM subscriptions AS s JOIN plans AS p ON p.plan_id = s.plan_id
        WHERE s.account_id = ?
        ORDER BY s.start_date
        """,
        (account_id,),
    ).fetchall()


def plan_in_effect(conn: sqlite3.Connection, account_id: str, day: date) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT s.plan_id, p.name, s.start_date, s.end_date, p.monthly_fee_minor,
               p.included_credits, p.overage_rate_minor_per_1k
        FROM subscriptions AS s JOIN plans AS p ON p.plan_id = s.plan_id
        WHERE s.account_id = :account_id
          AND s.start_date <= :day
          AND (s.end_date IS NULL OR s.end_date >= :day)
        """,
        {"account_id": account_id, "day": day.isoformat()},
    ).fetchone()


def usage_by_day(
    conn: sqlite3.Connection, account_id: str, first: date, last: date
) -> dict[date, int]:
    rows = conn.execute(
        "SELECT usage_date, credits FROM usage_daily "
        "WHERE account_id = ? AND usage_date BETWEEN ? AND ?",
        (account_id, first.isoformat(), last.isoformat()),
    ).fetchall()
    return {date.fromisoformat(r["usage_date"]): r["credits"] for r in rows}


def feed(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM feed_status WHERE feed = ?", (name,)).fetchone()


def feeds(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM feed_status ORDER BY feed").fetchall()


def fx_rates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM fx_rates ORDER BY currency").fetchall()


def invoice_position(
    conn: sqlite3.Connection, invoice_id: str, snapshot_date: date
) -> sqlite3.Row | None:
    return conn.execute(
        INVOICE_POSITIONS + " WHERE i.invoice_id = :invoice_id",
        {"invoice_id": invoice_id, "snapshot_date": snapshot_date.isoformat()},
    ).fetchone()


def account_invoice_positions(
    conn: sqlite3.Connection, account_id: str, snapshot_date: date
) -> list[sqlite3.Row]:
    return conn.execute(
        INVOICE_POSITIONS + " WHERE i.account_id = :account_id ORDER BY i.period_start",
        {"account_id": account_id, "snapshot_date": snapshot_date.isoformat()},
    ).fetchall()


def overdue_positions(
    conn: sqlite3.Connection, snapshot_date: date, min_days_overdue: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM (" + INVOICE_POSITIONS + ") "
        "WHERE balance_minor > 0 AND days_past_due >= :min_days "
        "ORDER BY days_past_due DESC, invoice_id",
        {"snapshot_date": snapshot_date.isoformat(), "min_days": min_days_overdue},
    ).fetchall()


def payments(conn: sqlite3.Connection, invoice_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT payment_id, paid_on, amount_minor FROM payments WHERE invoice_id = ? "
        "ORDER BY paid_on",
        (invoice_id,),
    ).fetchall()


def credit_notes(conn: sqlite3.Connection, invoice_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT credit_note_id, issued_on, amount_minor, reason FROM credit_notes "
        "WHERE invoice_id = ? ORDER BY issued_on",
        (invoice_id,),
    ).fetchall()


def usage_history_start(conn: sqlite3.Connection) -> date:
    return date.fromisoformat(conn.execute("SELECT MIN(usage_date) FROM usage_daily").fetchone()[0])
