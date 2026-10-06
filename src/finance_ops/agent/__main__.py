"""Ask Agent A a question.

python -m finance_ops.agent "Why did Kestrel Robotics' September invoice go up?"
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from finance_ops.agent.loop import DEFAULT_MAX_TURNS
from finance_ops.agent.runner import AgentSettings, ask, render
from finance_ops.config import db_path

ANSWERED = ("answered", "answered_with_data_warnings")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the finance-ops agent a question.")
    parser.add_argument("question")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--db", type=Path, default=db_path())
    parser.add_argument("--trace", action="store_true", help="list every tool call")
    args = parser.parse_args()

    load_dotenv()
    settings = AgentSettings.from_env()
    if not settings.api_key:
        sys.exit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add a key.")
    if not args.db.is_file():
        sys.exit(f"No database at {args.db}. Generate it with: make data")

    result, log_path = asyncio.run(
        ask(args.question, settings.model_client(), args.db, args.max_turns)
    )
    print(render(result, log_path, trace=args.trace))
    sys.exit(0 if result.status in ANSWERED else 1)


if __name__ == "__main__":
    main()
