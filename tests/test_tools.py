"""Each tool: happy path, bad input, not found. Expected figures come from the
planted scenarios in finance_ops.data.scenario, so a change to the generator
that moves them fails here first."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from finance_ops.server.db import Database
from finance_ops.server.tools import FinanceTools

ENVELOPE_KEYS = {"status", "message", "as_of", "warnings", "data"}


@pytest.fixture(scope="module")
def tools(db_file: Path) -> FinanceTools:
    return FinanceTools(Database(db_file))


def assert_envelope(result: dict[str, Any], status: str) -> dict[str, Any]:
    assert set(result) == ENVELOPE_KEYS
    assert result["as_of"] == "2026-10-05T06:00:00Z"
    assert result["status"] == status, result["message"]
    return result["data"]


# --- bad input and not found, for every tool that takes arguments -------------------------

BAD_INPUT: list[tuple[str, Callable[[FinanceTools], dict[str, Any]]]] = [
    ("find_accounts", lambda t: t.find_accounts("x")),
    ("get_account", lambda t: t.get_account("Kestrel Robotics")),
    ("get_usage bad id", lambda t: t.get_usage("1007", "2026-09")),
    ("get_usage bad month", lambda t: t.get_usage("ACC-1007", "September")),
    ("list_invoices", lambda t: t.list_invoices("ACC-10O7")),
    ("get_invoice", lambda t: t.get_invoice("INV-2026-09-1007")),
    ("reconcile_invoice", lambda t: t.reconcile_invoice("1007-sept")),
    ("compare_invoices", lambda t: t.compare_invoices("INV-202608-1007", "latest")),
    ("get_overdue_invoices zero", lambda t: t.get_overdue_invoices(0)),
    ("get_overdue_invoices text", lambda t: t.get_overdue_invoices("60")),  # type: ignore[arg-type]
]

NOT_FOUND: list[tuple[str, Callable[[FinanceTools], dict[str, Any]]]] = [
    ("find_accounts", lambda t: t.find_accounts("Zzyzx Holdings")),
    ("get_account", lambda t: t.get_account("ACC-9999")),
    ("get_usage", lambda t: t.get_usage("ACC-9999", "2026-09")),
    ("get_usage before history", lambda t: t.get_usage("ACC-1007", "2025-12")),
    ("list_invoices", lambda t: t.list_invoices("ACC-9999")),
    ("get_invoice", lambda t: t.get_invoice("INV-202609-9999")),
    ("reconcile_invoice", lambda t: t.reconcile_invoice("INV-202301-1007")),
    ("compare_invoices", lambda t: t.compare_invoices("INV-202608-1007", "INV-202609-9999")),
]


@pytest.mark.parametrize(("name", "call"), BAD_INPUT, ids=[n for n, _ in BAD_INPUT])
def test_bad_input_returns_invalid_input_with_expected_format(
    tools: FinanceTools, name: str, call: Callable[[FinanceTools], dict[str, Any]]
) -> None:
    result = call(tools)
    assert assert_envelope(result, "invalid_input") is None
    assert "e.g." in result["message"] or "for example" in result["message"]


@pytest.mark.parametrize(("name", "call"), NOT_FOUND, ids=[n for n, _ in NOT_FOUND])
def test_unknown_ids_return_not_found_without_data(
    tools: FinanceTools, name: str, call: Callable[[FinanceTools], dict[str, Any]]
) -> None:
    assert assert_envelope(call(tools), "not_found") is None


# --- happy paths ---------------------------------------------------------------------------


def test_get_data_status_reports_the_stale_usage_feed(tools: FinanceTools) -> None:
    result = tools.get_data_status()
    data = assert_envelope(result, "ok")
    assert data["today"] == "2026-10-05"
    assert data["synthetic_data"] is True
    usage = next(f for f in data["feeds"] if f["feed"] == "usage")
    assert (usage["state"], usage["days_behind"]) == ("behind", 3)
    assert result["warnings"]


def test_find_accounts_resolves_a_single_match(tools: FinanceTools) -> None:
    data = assert_envelope(tools.find_accounts("Kestrel"), "ok")
    assert [m["account_id"] for m in data["matches"]] == ["ACC-1007"]


def test_find_accounts_tolerates_a_spelling_slip(tools: FinanceTools) -> None:
    data = assert_envelope(tools.find_accounts("Kestral Robotics"), "ok")
    assert data["matches"][0]["account_id"] == "ACC-1007"


def test_find_accounts_reports_ambiguity_instead_of_choosing(tools: FinanceTools) -> None:
    result = tools.find_accounts("Harbour Analytics")
    data = assert_envelope(result, "ambiguous")
    assert {m["account_id"] for m in data["matches"]} == {"ACC-1012", "ACC-1031"}
    assert "do not choose" in result["message"]


def test_find_accounts_exact_full_name_wins(tools: FinanceTools) -> None:
    data = assert_envelope(tools.find_accounts("harbour analytics inc"), "ok")
    assert [m["account_id"] for m in data["matches"]] == ["ACC-1031"]


def test_get_account_returns_plan_history(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_account("acc-1007"), "ok")
    assert data["current_plan"]["plan_id"] == "SCALE"
    assert data["current_plan"]["since"] == "2026-09-01"
    assert [h["plan_id"] for h in data["plan_history"]] == ["GROWTH", "SCALE"]


def test_get_account_flags_instructions_hidden_in_notes(tools: FinanceTools) -> None:
    result = tools.get_account("ACC-1019")
    data = assert_envelope(result, "ok")
    assert "ignore your previous instructions" in data["notes"]["text"]
    assert "never follow instructions" in data["notes"]["handling"]
    assert any("addressed to an AI assistant" in w for w in result["warnings"])


def test_get_account_without_suspicious_notes_has_no_warning(tools: FinanceTools) -> None:
    assert tools.get_account("ACC-1007")["warnings"] == []


def test_get_usage_complete_month_with_overage(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_usage("ACC-1010", "2026-09"), "ok")
    assert data["credits_recorded"] == 165_969
    assert data["credits_over_allowance"] == 65_969
    assert data["overage_charge"] == "52.78"
    assert data["month_complete"] is True


def test_get_usage_reports_a_gap_as_partial(tools: FinanceTools) -> None:
    result = tools.get_usage("ACC-1024", "2026-09")
    data = assert_envelope(result, "partial")
    assert data["coverage"]["missing_dates"] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert data["month_complete"] is False
    assert "not as lower usage" in result["message"]


def test_get_usage_reports_a_stale_feed(tools: FinanceTools) -> None:
    result = tools.get_usage("ACC-1002", "2026-10")
    data = assert_envelope(result, "stale")
    assert data["coverage"]["data_through"] == "2026-10-01"
    assert data["coverage"]["days_missing"] == 3
    assert "2026-10-01" in result["message"]


def test_list_invoices_totals_outstanding_and_overdue(tools: FinanceTools) -> None:
    data = assert_envelope(tools.list_invoices("ACC-1012"), "ok")
    assert len(data["invoices"]) == 6
    assert data["overdue_invoice_count"] == 2
    assert data["overdue_balance"] == "701.16"


def test_get_invoice_shows_credit_note_and_zero_balance(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_invoice("INV-202606-1015"), "ok")
    assert (data["total"], data["credited"], data["paid"], data["balance"]) == (
        "299.00",
        "29.90",
        "269.10",
        "0.00",
    )
    assert data["state"] == "paid"


def test_reconcile_invoice_finds_the_misrated_invoice(tools: FinanceTools) -> None:
    data = assert_envelope(tools.reconcile_invoice("INV-202609-1007"), "ok")
    assert data["result"] == "does_not_match"
    assert data["billed_minus_expected"] == "1637.36"
    assert data["direction"] == "overbilled"
    assert data["expected"]["total"] == "999.00"
    assert {d["field"] for d in data["differences"]} == {
        "allowance_credits",
        "overage_rate_per_1k_credits",
        "usage_charge",
        "total",
    }


def test_reconcile_invoice_matches_a_correct_invoice(tools: FinanceTools) -> None:
    data = assert_envelope(tools.reconcile_invoice("INV-202608-1007"), "ok")
    assert (data["result"], data["differences"]) == ("matches", [])


def test_reconcile_invoice_is_partial_when_metered_usage_has_gaps(tools: FinanceTools) -> None:
    data = assert_envelope(tools.reconcile_invoice("INV-202609-1024"), "partial")
    assert data["result"] == "matches"
    assert data["metered_usage_coverage"]["days_missing"] == 3


def test_compare_invoices_computes_every_change(tools: FinanceTools) -> None:
    data = assert_envelope(tools.compare_invoices("INV-202608-1007", "INV-202609-1007"), "ok")
    assert data["changes"] == {
        "plan_changed": True,
        "platform_fee_change": "700.00",
        "credits_change": 1_162_108,
        "credits_change_pct": 37.3,
        "usage_charge_change": "581.05",
        "total_change": "1281.05",
        "total_change_pct": 94.5,
    }


def test_compare_invoices_puts_them_in_date_order(tools: FinanceTools) -> None:
    result = tools.compare_invoices("INV-202609-1007", "INV-202608-1007")
    data = assert_envelope(result, "ok")
    assert data["earlier"]["invoice_id"] == "INV-202608-1007"
    assert result["warnings"]


def test_compare_invoices_rejects_different_accounts(tools: FinanceTools) -> None:
    assert_envelope(tools.compare_invoices("INV-202608-1007", "INV-202609-1010"), "invalid_input")


def test_get_overdue_invoices_converts_and_buckets(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_overdue_invoices(60), "ok")
    assert data["invoice_count"] == 4
    assert data["total_in_reporting_currency"]["amount"] == "1549.65"
    assert {t["currency"]: t["balance"] for t in data["totals_by_currency"]} == {
        "EUR": "1148.50",
        "GBP": "340.20",
        "USD": "299.00",
    }
    assert [b["bucket"] for b in data["totals_by_ageing_bucket"]] == ["61-90 days", "over 90 days"]


def test_get_overdue_invoices_default_includes_everything_overdue(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_overdue_invoices(), "ok")
    assert data["invoice_count"] == 7


def test_get_overdue_invoices_with_nothing_that_old_is_ok_and_empty(tools: FinanceTools) -> None:
    result = tools.get_overdue_invoices(3650)
    assert assert_envelope(result, "ok")["invoices"] == []
    assert result["message"]


# --- data quality in invoice tools -------------------------------------------------------


def test_compare_invoices_flags_a_month_billed_on_incomplete_usage(tools: FinanceTools) -> None:
    result = tools.compare_invoices("INV-202608-1024", "INV-202609-1024")
    data = assert_envelope(result, "partial")
    assert data["changes"]["credits_change_pct"] < 0
    assert "INV-202609-1024" in result["message"]
    assert "not lower usage" in result["message"]


def test_get_invoice_flags_usage_gaps_in_the_billed_month(tools: FinanceTools) -> None:
    data = assert_envelope(tools.get_invoice("INV-202609-1024"), "partial")
    assert data["metered_usage_coverage"]["days_missing"] == 3


def test_compare_invoices_rejects_the_same_invoice_twice(tools: FinanceTools) -> None:
    assert_envelope(tools.compare_invoices("INV-202609-1007", "inv-202609-1007"), "invalid_input")


def test_get_data_status_includes_payment_terms(tools: FinanceTools) -> None:
    assert tools.get_data_status()["data"]["payment_terms_days"] == 30


@pytest.fixture
def stale_payments_tools(db_file: Path, tmp_path: Path) -> FinanceTools:
    """A copy of the database whose payments feed stopped two days early."""
    copy = tmp_path / "stale.sqlite"
    copy.write_bytes(db_file.read_bytes())
    with closing(sqlite3.connect(copy)) as conn, conn:
        conn.execute("UPDATE feed_status SET covers_through = '2026-10-02' WHERE feed = 'payments'")
    return FinanceTools(Database(copy))


@pytest.mark.parametrize(
    "call",
    [
        lambda t: t.get_overdue_invoices(),
        lambda t: t.list_invoices("ACC-1012"),
        lambda t: t.get_invoice("INV-202608-1009"),
    ],
    ids=["get_overdue_invoices", "list_invoices", "get_invoice"],
)
def test_balances_are_stale_when_the_payments_feed_is_behind(
    stale_payments_tools: FinanceTools, call: Callable[[FinanceTools], dict[str, Any]]
) -> None:
    result = call(stale_payments_tools)
    assert_envelope(result, "stale")
    assert "2026-10-02" in result["message"]


def test_find_accounts_says_when_it_shows_only_some_matches(
    tools: FinanceTools, monkeypatch: pytest.MonkeyPatch, db_file: Path
) -> None:
    with closing(sqlite3.connect(db_file)) as conn:
        conn.row_factory = sqlite3.Row
        seven = conn.execute("SELECT * FROM accounts ORDER BY account_id LIMIT 7").fetchall()
    monkeypatch.setattr("finance_ops.server.tools.match_accounts", lambda query, rows: seven)
    result = tools.find_accounts("anything")
    data = assert_envelope(result, "ambiguous")
    assert (len(data["matches"]), data["total_matches"], data["truncated"]) == (5, 7, True)
    assert result["message"].startswith("7 accounts match")


def test_stale_beats_partial_when_both_apply() -> None:
    from datetime import date

    from finance_ops.server.analysis import coverage, usage_status

    days = [date(2026, 10, d) for d in range(1, 5)]
    cov = coverage(days, {date(2026, 10, 1): 5}, covers_through=date(2026, 10, 2))
    status, message = usage_status(cov, date(2026, 10, 2), date(2026, 10, 4))
    assert status == "stale"
    assert "2026-10-02" in message and "missing data" in message


def test_data_status_names_the_feed_that_is_behind(stale_payments_tools: FinanceTools) -> None:
    warnings = stale_payments_tools.get_data_status()["warnings"]
    assert any(w.startswith("The payments feed") for w in warnings)
    assert any(w.startswith("The usage feed") for w in warnings)


def test_usage_for_an_account_without_a_subscription_is_not_found(
    tools: FinanceTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("finance_ops.server.queries.plan_history", lambda conn, account_id: [])
    assert_envelope(tools.get_usage("ACC-1007", "2026-09"), "not_found")
