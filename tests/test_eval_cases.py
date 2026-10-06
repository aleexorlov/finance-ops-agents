"""The evaluation's own correctness: case file, grading rules, fault injection, report."""

import typing
from pathlib import Path
from typing import Any

import anyio
import pytest
from fakes import FakeTools, envelope

from finance_ops.agent.types import RunResult, RunStatus, TokenUsage, ToolCall, ToolCallRecord
from finance_ops.evals.grading import Case, grade, load_cases, mentions_figure
from finance_ops.evals.harness import SIMULATED_OUTAGE, FailingTools, RunRecord
from finance_ops.evals.report import estimate, render_markdown
from finance_ops.server.app import TOOL_NAMES
from finance_ops.server.db import Database
from finance_ops.server.tools import FinanceTools

CASES = load_cases(Path(__file__).resolve().parents[1] / "evals" / "cases.toml")
RUN_STATUSES = set(typing.get_args(RunStatus))


def lookup(envelope_: dict[str, Any], path: str) -> Any:
    value: Any = envelope_
    for part in path.split("."):
        value = value[int(part)] if part.isdigit() else value[part]
    return value


# --- the case file -----------------------------------------------------------------------


def test_between_ten_and_fifteen_cases_with_unique_ids() -> None:
    assert 10 <= len(CASES) <= 15
    assert len({c.id for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case_refers_only_to_real_statuses_and_tools(case: Case) -> None:
    assert set(case.expect_status) <= RUN_STATUSES
    assert set(case.required_tools) <= set(TOOL_NAMES)
    assert set(case.failing_tools) <= set(TOOL_NAMES)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_every_expected_figure_is_backed_by_evidence(case: Case) -> None:
    backed = {e.value for e in case.evidence}
    assert set(case.figures) <= backed
    assert set(case.any_figure) <= backed


@pytest.mark.parametrize(
    "evidence",
    [e for c in CASES for e in c.evidence],
    ids=[f"{c.id}:{e.path}" for c in CASES for e in c.evidence],
)
def test_evidence_matches_what_the_tools_return(db_file: Path, evidence: Any) -> None:
    tools = FinanceTools(Database(db_file))
    result = getattr(tools, evidence.tool)(**evidence.args)
    assert str(lookup(result, evidence.path)) == evidence.value


# --- grading -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected", "found"),
    [
        ("Overbilled by £1,637.36.", "1637.36", True),
        ("Overbilled by about £1,637.", "1637.36", True),
        ("The fee is €4,000 a month.", "4000.00", True),
        ("65,969 credits over", "65969", True),
        ("Overbilled by £1,673.36.", "1637.36", False),
        ("1.6k over", "1637.36", False),
    ],
)
def test_mentions_figure(text: str, expected: str, found: bool) -> None:
    assert mentions_figure(text, expected) is found


CASE = Case(
    id="t",
    checks="",
    question="?",
    expect_status=("answered",),
    figures=("1637.36",),
    any_of=(("Scale",),),
    none_of=("I have emailed",),
    required_tools=("reconcile_invoice",),
)


def result(status: RunStatus, answer: str | None, tools: tuple[str, ...] = ()) -> RunResult:
    records = tuple(
        ToolCallRecord(1, ToolCall(str(i), name, {}), "ok", False, 1.0)
        for i, name in enumerate(tools)
    )
    return RunResult("r", "?", status, answer, answer, 1, tool_calls=records)


def test_grade_pass() -> None:
    graded = grade(
        CASE, result("answered", "Moved to Scale; overbilled £1,637.36.", ("reconcile_invoice",))
    )
    assert (graded.bucket, graded.failures) == ("pass", ())


def test_grade_lists_every_content_failure() -> None:
    graded = grade(CASE, result("answered", "Fine. I have emailed the client.", ()))
    assert graded.bucket == "wrong_content"
    assert graded.failures == (
        "missing figure 1637.36",
        "mentions none of ['Scale']",
        "says 'I have emailed'",
        "did not call reconcile_invoice",
    )


def test_grade_unexpected_status_and_error() -> None:
    assert grade(CASE, result("blocked_unverified_figures", None)).bucket == "unexpected_status"
    errored = RunResult("r", "?", "model_error", None, None, 1, error="overloaded")
    assert grade(CASE, errored).bucket == "error"


# --- fault injection and reporting -------------------------------------------------------


def test_failing_tools_fail_only_the_named_tools() -> None:
    wrapped = FailingTools(FakeTools(get_invoice=envelope(total="1.00")), ("get_invoice",))
    failed = anyio.run(wrapped.call, "get_invoice", {})
    passed = anyio.run(wrapped.call, "get_data_status", {})
    assert (failed.is_error, failed.text) == (True, SIMULATED_OUTAGE)
    assert passed.is_error is False


def test_report_and_estimate_render(tmp_path: Path) -> None:
    case = CASES[0]
    records = [
        RunRecord(
            case.id, n, "answered", bucket, (), 2, (), TokenUsage(1000, 100), 0.003, 1.0, "a", "x"
        )
        for n, bucket in [(1, "pass"), (2, "wrong_content")]
    ]
    meta = {"model": "claude-sonnet-5-5", "started": "2026-10-06T18:00:00", "repeats": 2}
    markdown = render_markdown([case], records, meta)
    assert f"| `{case.id}` |" in markdown
    assert "1/2 runs passed (50.0%)" in markdown
    assert "assumed 15,000 input" in estimate(15, 5, "claude-sonnet-5-5", tmp_path)
