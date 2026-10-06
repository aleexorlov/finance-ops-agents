import sqlite3
from contextlib import closing
from pathlib import Path

from finance_ops.data.generate import write_database


def query(db_file: Path, sql: str, params: tuple = ()) -> list[tuple]:
    with closing(sqlite3.connect(db_file)) as conn:
        return conn.execute(sql, params).fetchall()


def dump(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        return list(conn.iterdump())


def test_same_seed_produces_identical_database(tmp_path: Path) -> None:
    write_database(tmp_path / "a.sqlite", seed=7)
    write_database(tmp_path / "b.sqlite", seed=7)
    assert dump(tmp_path / "a.sqlite") == dump(tmp_path / "b.sqlite")


def test_different_seed_produces_different_data(tmp_path: Path) -> None:
    write_database(tmp_path / "a.sqlite", seed=7)
    write_database(tmp_path / "b.sqlite", seed=8)
    assert dump(tmp_path / "a.sqlite") != dump(tmp_path / "b.sqlite")


def test_database_is_labelled_synthetic(db_file: Path) -> None:
    meta = dict(query(db_file, "SELECT key, value FROM meta"))
    assert meta["synthetic"] == "true"
    assert "No real customers" in meta["notice"]


def test_planted_misrated_invoice_uses_old_plan_terms(db_file: Path) -> None:
    [(plan_billed, allowance, rate)] = query(
        db_file,
        "SELECT plan_id_billed, allowance_applied, overage_rate_applied_minor_per_1k "
        "FROM invoices WHERE invoice_id = 'INV-202609-1007'",
    )
    assert plan_billed == "SCALE"
    assert (allowance, rate) == (1_000_000, 50)  # Growth terms, not Scale's 5,000,000 at 30


def test_other_invoices_are_rated_on_the_plan_billed(db_file: Path) -> None:
    rows = query(
        db_file,
        "SELECT i.invoice_id FROM invoices i JOIN plans p ON p.plan_id = i.plan_id_billed "
        "WHERE i.allowance_applied != p.included_credits "
        "OR i.overage_rate_applied_minor_per_1k != p.overage_rate_minor_per_1k",
    )
    assert rows == [("INV-202609-1007",)]


def test_planted_usage_gap_has_no_rows(db_file: Path) -> None:
    rows = query(
        db_file,
        "SELECT usage_date FROM usage_daily WHERE account_id = 'ACC-1024' "
        "AND usage_date BETWEEN '2026-09-20' AND '2026-09-24' ORDER BY usage_date",
    )
    assert rows == [("2026-09-20",), ("2026-09-24",)]


def test_usage_feed_is_behind_at_snapshot(db_file: Path) -> None:
    [(covers, expected)] = query(
        db_file, "SELECT covers_through, expected_through FROM feed_status WHERE feed = 'usage'"
    )
    assert covers < expected
    [(latest,)] = query(db_file, "SELECT MAX(usage_date) FROM usage_daily")
    assert latest == covers


def test_only_planted_invoices_are_overdue(db_file: Path) -> None:
    rows = query(
        db_file,
        """
        SELECT i.invoice_id
        FROM invoices i
        LEFT JOIN (SELECT invoice_id, SUM(amount_minor) AS paid FROM payments GROUP BY 1) p
            USING (invoice_id)
        LEFT JOIN (SELECT invoice_id, SUM(amount_minor) AS credited FROM credit_notes GROUP BY 1) c
            USING (invoice_id)
        WHERE i.total_minor - COALESCE(p.paid, 0) - COALESCE(c.credited, 0) > 0
          AND i.due_on < '2026-10-05'
        ORDER BY i.invoice_id
        """,
    )
    assert [r[0] for r in rows] == [
        "INV-202604-1031",
        "INV-202605-1022",
        "INV-202606-1012",
        "INV-202606-1033",
        "INV-202607-1012",
        "INV-202607-1019",
        "INV-202608-1009",
    ]


def test_two_accounts_share_a_name(db_file: Path) -> None:
    rows = query(db_file, "SELECT account_id FROM accounts WHERE name LIKE 'Harbour Analytics%'")
    assert sorted(r[0] for r in rows) == ["ACC-1012", "ACC-1031"]


def test_account_names_are_unique(db_file: Path) -> None:
    [(total, distinct)] = query(db_file, "SELECT COUNT(*), COUNT(DISTINCT name) FROM accounts")
    assert total == distinct == 40
