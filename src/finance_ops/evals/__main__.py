"""Run the known-answer evaluation against Agent A.

    python -m finance_ops.evals --estimate        # cost estimate, no API calls
    python -m finance_ops.evals --repeats 5       # full run (needs ANTHROPIC_API_KEY)
    python -m finance_ops.evals --only invoice-jump --repeats 1

Without an API key it exits cleanly and runs nothing. Results go to
evals/results/<stamp>.json (every run) and evals/results/latest.md (the table).
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import anyio
from dotenv import load_dotenv

from finance_ops.agent.runner import AgentSettings
from finance_ops.config import db_path
from finance_ops.evals.grading import load_cases
from finance_ops.evals.harness import run_all, save_records
from finance_ops.evals.report import estimate, render_markdown

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CASES = REPO / "evals" / "cases.toml"
RESULTS_DIR = REPO / "evals" / "results"


def main() -> None:
    parser = argparse.ArgumentParser(description="Known-answer evaluation for Agent A.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--only", help="comma-separated case IDs")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--estimate", action="store_true", help="print a cost estimate and exit")
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    settings = AgentSettings.from_env()
    cases = load_cases(args.cases)
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]
        if missing := wanted - {c.id for c in cases}:
            sys.exit(f"Unknown case IDs: {', '.join(sorted(missing))}")

    if args.estimate:
        print(estimate(len(cases), args.repeats, settings.model, RESULTS_DIR))
        return
    if not settings.api_key:
        print("ANTHROPIC_API_KEY is not set, so the evaluation was skipped. Nothing was run.")
        return
    database = db_path()
    if not database.is_file():
        sys.exit(f"No database at {database}. Generate it with: make data")

    started = datetime.now(UTC)
    print(f"Running {len(cases)} cases x {args.repeats} on {settings.model}...")
    records = anyio.run(
        lambda: run_all(
            cases,
            args.repeats,
            settings.model_client(),
            settings.model,
            database,
            REPO / "runs",
            args.concurrency,
        )
    )
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    meta = {"model": settings.model, "started": started.isoformat(), "repeats": args.repeats}
    # Runs of selected cases are trials: kept locally (partial-*.json is gitignored).
    prefix = "partial-" if args.only else ""
    save_records(records, RESULTS_DIR / f"{prefix}{stamp}.json", meta)
    markdown = render_markdown(cases, records, meta)
    if not args.only:
        (RESULTS_DIR / f"{stamp}.md").write_text(markdown, encoding="utf-8")
        (RESULTS_DIR / "latest.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
