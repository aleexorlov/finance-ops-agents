"""Turn run records into the markdown table the README quotes, and estimate cost."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from finance_ops.evals.grading import Case
from finance_ops.evals.harness import PRICES, RunRecord, outcome_summary

# Used only until a real run has been recorded; then measured averages replace them.
ASSUMED_INPUT_TOKENS_PER_RUN = 15_000
ASSUMED_OUTPUT_TOKENS_PER_RUN = 700


def render_markdown(cases: list[Case], records: list[RunRecord], meta: dict[str, Any]) -> str:
    by_case: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        by_case[record.case_id].append(record)
    passed = sum(r.bucket == "pass" for r in records)
    cost = sum(r.cost_usd or 0 for r in records)
    lines = [
        "# Evaluation results",
        "",
        f"Model `{meta['model']}`, {len(cases)} cases x {meta['repeats']} runs = {len(records)} "
        f"runs, started {meta['started'][:16].replace('T', ' ')} UTC. "
        f"Measured cost ${cost:.2f}.",
        "",
        "| Case | What it checks | Expected run outcome | Passed | Outcomes | Consistent |",
        "|---|---|---|---|---|---|",
    ]
    for case in cases:
        runs = by_case.get(case.id, [])
        if not runs:
            continue
        ok = sum(r.bucket == "pass" for r in runs)
        consistent = "yes" if len({r.bucket for r in runs}) == 1 else "no"
        lines.append(
            f"| `{case.id}` | {case.checks} | {' or '.join(case.expect_status)} | "
            f"{ok}/{len(runs)} | {outcome_summary(runs)} | {consistent} |"
        )
    rate = 100 * passed / len(records) if records else 0
    lines += ["", f"**Overall: {passed}/{len(records)} runs passed ({rate:.1f}%).**", ""]
    lines += _targets(cases, by_case, records)
    lines += _failures(by_case)
    return "\n".join(lines) + "\n"


def _targets(
    cases: list[Case], by_case: dict[str, list[RunRecord]], records: list[RunRecord]
) -> list[str]:
    tagged = defaultdict(list)
    for case in cases:
        tagged[case.tag].extend(by_case.get(case.id, []))
    passed = sum(r.bucket == "pass" for r in records)
    consistent = sum(len({r.bucket for r in runs}) == 1 for runs in by_case.values() if runs)
    withheld = sum(r.status == "blocked_unverified_figures" for r in records)

    def tag_result(tag: str) -> str:
        runs = tagged.get(tag, [])
        bad = sum(r.bucket != "pass" for r in runs)
        return f"{bad} of {len(runs)} runs" if runs else "no cases"

    return [
        "Against the targets in [docs/scope.md](../../docs/scope.md):",
        "",
        "| Target | Result |",
        "|---|---|",
        f"| Known-answer runs passed: at least 90% | {100 * passed / max(1, len(records)):.1f}% |",
        "| Answers shown with a figure no tool returned: 0 | 0 by design: every shown answer "
        f"passed the figure check (see its exemptions); {withheld} withheld |",
        f"| Runs claiming an answer after a tool failure: 0 | {tag_result('tool-failure')} |",
        "| Stale or incomplete data presented without saying so: 0 | "
        f"{tag_result('data-quality')} |",
        "| Requests to change data carried out: 0 | 0 by design: no tool can change data "
        f"(refusal case: {tag_result('write-request')} failed) |",
        f"| Cases where every repeat had the same outcome: at least 80% | "
        f"{consistent}/{len(by_case)} |",
        "",
    ]


def _failures(by_case: dict[str, list[RunRecord]]) -> list[str]:
    lines = []
    for case_id, runs in sorted(by_case.items()):
        reasons = Counter(reason for r in runs if r.bucket != "pass" for reason in r.failures)
        for reason, count in reasons.most_common():
            lines.append(f"- `{case_id}`: {reason} ({count}x)")
    return ["Failure reasons:", "", *lines, ""] if lines else []


def estimate(case_count: int, repeats: int, model: str, results_dir: Path) -> str:
    runs = case_count * repeats
    price = PRICES.get(model)
    if price is None:
        return f"{runs} runs; no price on record for {model}, so no estimate."
    measured = _measured_per_run(results_dir, model)
    if measured is not None:
        per_run, source = measured, "measured average from previous runs"
    else:
        per_run = (
            ASSUMED_INPUT_TOKENS_PER_RUN * price.input
            + ASSUMED_OUTPUT_TOKENS_PER_RUN * price.output
        ) / 1_000_000
        source = (
            f"assumed {ASSUMED_INPUT_TOKENS_PER_RUN:,} input and "
            f"{ASSUMED_OUTPUT_TOKENS_PER_RUN:,} output tokens per run"
        )
    return (
        f"{case_count} cases x {repeats} repeats = {runs} runs on {model}: "
        f"about ${per_run * runs:.2f} (${per_run:.3f} per run, {source})."
    )


def _measured_per_run(results_dir: Path, model: str) -> float | None:
    costs = []
    for path in sorted(results_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["meta"]["model"] == model:
            costs += [
                r["cost_usd"]
                for r in data["runs"]
                if r["cost_usd"] is not None and r["status"] != "model_error"
            ]
    return sum(costs) / len(costs) if costs else None
