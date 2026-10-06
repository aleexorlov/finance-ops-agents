"""Deterministic grading of one agent run against a known-answer case.

No model grades another model here: every check is a rule a reader can verify.
A run lands in exactly one bucket:

  pass               the run ended as expected and the answer met every check
  wrong_content      the run ended as expected, but a required fact was missing
                     or a forbidden claim was present
  unexpected_status  the run ended some other way (for example withheld for an
                     unverified figure, or stopped at the step cap)
  error              the model API failed

The rules were tested adversarially before the first full run: reviewers wrote
correct answers in varied styles and wrong answers a flawed agent might give,
and the phrase lists were tightened until both kinds were graded correctly.
"""

import re
import tomllib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from finance_ops.agent.grounding import NOT_FIGURES, answer_figures, is_grounded
from finance_ops.agent.types import RunResult

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Curly apostrophes, Unicode hyphens and non-breaking spaces become plain ASCII,
# so a curly "I've marked" is caught by "i've marked", and IDs typed with a
# non-breaking hyphen still match.
NORMALISE = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2212": "-", "\u00a0": " ", "\u202f": " ",
})  # fmt: skip
TUPLE_FIELDS = (
    "expect_status", "figures", "any_figure", "all_or_none_figures", "none_of",
    "none_match", "required_tools", "failing_tools",
)  # fmt: skip


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
    all_or_none_figures: tuple[str, ...] = ()  # stating some but not all = chose one
    any_of: tuple[tuple[str, ...], ...] = ()  # each group: at least one phrase must appear
    none_of: tuple[str, ...] = ()  # none of these phrases may appear
    none_match: tuple[str, ...] = ()  # regexes (case-insensitive) that must not match
    headline_no_figures: bool = False  # the first line must not state a figure
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
    plain = {k: v for k, v in entry.items() if k not in (*TUPLE_FIELDS, "any_of", "evidence")}
    return Case(
        **plain,
        **{k: tuple(v) for k, v in entry.items() if k in TUPLE_FIELDS},
        any_of=tuple(tuple(group) for group in entry.get("any_of", ())),
        evidence=tuple(Evidence(**e) for e in entry.get("evidence", ())),
    )


def mentions_figure(text: str, expected: str) -> bool:
    """True if `text` states `expected`.

    Allows thousands separators and rounding to fewer decimal places (4,000 states
    4000.00; 1,637 states 1637.36), and scaled forms the figure check also accepts
    (1.55k states 1549.65). IDs and dates are masked first, so the 30 in
    "2026-06-30" does not count as stating 29.90.
    """
    target = Decimal(expected)
    masked = NOT_FIGURES.sub(" ", text)
    for token in NUMBER.findall(masked):
        number = token.replace(",", "").rstrip(".")
        places = len(number.split(".")[1]) if "." in number else 0
        if places == 0 and target != target.to_integral_value() and target < 100:
            continue  # "30 days" must not count as stating 29.90
        quantum = Decimal(1).scaleb(-places)
        if target.quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(number):
            return True
    return any(f.scale != 1 and is_grounded(f, {target}) for f in answer_figures(text))


def grade(case: Case, result: RunResult) -> Grade:
    if result.status == "model_error":
        return Grade("error", (result.error or "model error",))
    if result.status not in case.expect_status:
        return Grade("unexpected_status", (f"ended as {result.status}",))
    failures = _content_failures(case, (result.answer or "").translate(NORMALISE))
    called = {record.call.name for record in result.tool_calls}
    failures += [f"did not call {tool}" for tool in case.required_tools if tool not in called]
    return Grade("wrong_content" if failures else "pass", tuple(failures))


def _content_failures(case: Case, text: str) -> list[str]:
    lowered = text.lower()
    failures = [f"missing figure {f}" for f in case.figures if not mentions_figure(text, f)]
    if case.any_figure and not any(mentions_figure(text, f) for f in case.any_figure):
        failures.append(f"mentions none of the figures {list(case.any_figure)}")
    stated = [f for f in case.all_or_none_figures if mentions_figure(text, f)]
    if stated and len(stated) < len(case.all_or_none_figures):
        failures.append(f"states only {stated} of {list(case.all_or_none_figures)}")
    failures += [
        f"mentions none of {list(group)}"
        for group in case.any_of
        if not any(phrase.lower() in lowered for phrase in group)
    ]
    failures += [f"says {phrase!r}" for phrase in case.none_of if phrase.lower() in lowered]
    failures += [f"matches {p!r}" for p in case.none_match if re.search(p, text, re.IGNORECASE)]
    headline = next((line for line in text.splitlines() if line.strip()), "")
    if case.headline_no_figures and answer_figures(headline):
        failures.append("states a figure in the first line")
    return failures
