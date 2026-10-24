"""Compare evaluation runs across models, side by side.

    python -m finance_ops.evals.compare evals/results/A.json evals/results/B.json ...

Prints a markdown summary table (one row per run) and a case-by-case pass matrix.
"""

import json
import statistics
import sys
from pathlib import Path
from typing import Any


def summarise(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data["runs"]
    by_case: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_case.setdefault(run["case_id"], []).append(run)
    passed = sum(r["bucket"] == "pass" for r in runs)
    cost = sum(r["cost_usd"] or 0 for r in runs)
    return {
        "model": data["meta"]["model"],
        "file": path.name,
        "runs": len(runs),
        "passed": passed,
        "withheld": sum(r["status"] == "blocked_unverified_figures" for r in runs),
        "consistent": sum(len({r["bucket"] for r in rs}) == 1 for rs in by_case.values()),
        "cases": len(by_case),
        "turns": statistics.mean(r["turns"] for r in runs),
        "tool_calls": statistics.mean(len(r["tool_calls"]) for r in runs),
        "seconds": statistics.median(r["seconds"] for r in runs),
        "cost": cost,
        "cost_per_pass": cost / passed if passed else None,
        "per_case": {case: sum(r["bucket"] == "pass" for r in rs) for case, rs in by_case.items()},
    }


def render(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "| Model | Passed | Withheld | Consistent cases | Turns | Tool calls | Median s "
        "| Cost | Cost per passing answer |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        per_pass = f"${s['cost_per_pass']:.4f}" if s["cost_per_pass"] is not None else "n/a"
        lines.append(
            f"| `{s['model']}` | {s['passed']}/{s['runs']} ({100 * s['passed'] / s['runs']:.1f}%) "
            f"| {s['withheld']} | {s['consistent']}/{s['cases']} | {s['turns']:.1f} "
            f"| {s['tool_calls']:.1f} | {s['seconds']:.1f} | ${s['cost']:.2f} | {per_pass} |"
        )
    cases = list(summaries[0]["per_case"])
    lines += [
        "",
        "| Case | " + " | ".join(f"`{s['model']}`" for s in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    for case in cases:
        cells = " | ".join(f"{s['per_case'].get(case, 0)}/5" for s in summaries)
        lines.append(f"| `{case}` | {cells} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        sys.exit("usage: python -m finance_ops.evals.compare RESULTS.json [RESULTS.json ...]")
    print(render([summarise(p) for p in paths]))


if __name__ == "__main__":
    main()
