"""Deterministic grading of one agent run against a known-answer case.

No model grades another model here: every check is a rule a reader can verify.
A run lands in exactly one bucket:

  pass               the run ended as expected and the answer met every check
  wrong_content      the run ended as expected, but a required fact was missing
                     or a forbidden claim was present
  unexpected_status  the run ended some other way (for example withheld for an
                     unverified figure, or stopped at the step cap)
  error              the model API failed
"""

import re
import tomllib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from finance_ops.agent.types import RunResult

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Evidence:
    """Where an expected figure comes from: a tool call and a path into its data."""

    tool: str
    args: dict[str, Any]
    path: str
    value: str


@dataclass(frozen=True)
class Case:
    id: str
    checks: str  # one line: what this case is for
    question: str
    expect_status: tuple[str, ...]
    figures: tuple[str, ...] = ()  # each must appear in the answer
    any_figure: tuple[str, ...] = ()  # at least one of these must appear
    any_of: tuple[tuple[str, ...], ...] = ()  # each group: at least one phrase must appear
    none_of: tuple[str, ...] = ()  # none of these phrases may appear
    required_tools: tuple[str, ...] = ()  # each must have been called during the run
    max_turns: int | None = None
    failing_tools: tuple[str, ...] = ()  # tools forced to fail for this case
    tag: str = "general"  # groups cases when results are compared with the scope targets
    evidence: tuple[Evidence, ...] = field(default=())


@dataclass(frozen=True)
class Grade:
    bucket: str
    failures: tuple[str, ...]


def load_cases(path: Path) -> list[Case]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return [_case(entry) for entry in raw["case"]]


def _case(entry: dict[str, Any]) -> Case:
    return Case(
        id=entry["id"],
        checks=entry["checks"],
        question=entry["question"],
        expect_status=tuple(entry["expect_status"]),
        figures=tuple(entry.get("figures", ())),
        any_figure=tuple(entry.get("any_figure", ())),
        any_of=tuple(tuple(group) for group in entry.get("any_of", ())),
        none_of=tuple(entry.get("none_of", ())),
        required_tools=tuple(entry.get("required_tools", ())),
        max_turns=entry.get("max_turns"),
        failing_tools=tuple(entry.get("failing_tools", ())),
        tag=entry.get("tag", "general"),
        evidence=tuple(Evidence(**e) for e in entry.get("evidence", ())),
    )


def mentions_figure(text: str, expected: str) -> bool:
    """True if `text` states `expected`, allowing thousands separators and rounding
    to fewer decimal places (so 4,000 states 4000.00, and 1,637 states 1637.36)."""
    target = Decimal(expected)
    for token in NUMBER.findall(text):
        number = token.replace(",", "").rstrip(".")
        places = len(number.split(".")[1]) if "." in number else 0
        quantum = Decimal(1).scaleb(-places)
        if target.quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(number):
            return True
    return False


def grade(case: Case, result: RunResult) -> Grade:
    if result.status == "model_error":
        return Grade("error", (result.error or "model error",))
    if result.status not in case.expect_status:
        return Grade("unexpected_status", (f"ended as {result.status}",))
    text = result.answer or ""
    lowered = text.lower()
    failures = [f"missing figure {f}" for f in case.figures if not mentions_figure(text, f)]
    if case.any_figure and not any(mentions_figure(text, f) for f in case.any_figure):
        failures.append(f"mentions none of the figures {list(case.any_figure)}")
    failures += [
        f"mentions none of {list(group)}"
        for group in case.any_of
        if not any(phrase.lower() in lowered for phrase in group)
    ]
    failures += [f"says {phrase!r}" for phrase in case.none_of if phrase.lower() in lowered]
    called = {record.call.name for record in result.tool_calls}
    failures += [f"did not call {tool}" for tool in case.required_tools if tool not in called]
    return Grade("wrong_content" if failures else "pass", tuple(failures))
