"""Run every case several times against Agent A and summarise the results."""

import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import anyio

from finance_ops.agent.executor import ToolExecutor
from finance_ops.agent.model import ModelClient
from finance_ops.agent.runner import ask
from finance_ops.agent.types import TokenUsage, ToolOutcome, ToolSpec
from finance_ops.evals.grading import Case, grade

SIMULATED_OUTAGE = "Tool call failed: simulated outage (evaluation fault injection)."


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


# From platform.claude.com/docs/en/about-claude/pricing, checked 2026-10-06.
PRICES = {
    "claude-sonnet-5-5": Price(2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5": Price(4.00, 20.00, 5.00, 0.20),
    "claude-haiku-4-5-20251001": Price(1.00, 5.00, 1.25, 0.10),
}


def cost_usd(usage: TokenUsage, model: str) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_write_tokens * price.cache_write
        + usage.cache_read_tokens * price.cache_read
    ) / 1_000_000


class FailingTools:
    """Wraps an executor so the named tools fail, to test how the agent handles outages."""

    def __init__(self, inner: ToolExecutor, failing: tuple[str, ...]) -> None:
        self._inner = inner
        self._failing = frozenset(failing)

    async def list_tools(self) -> list[ToolSpec]:
        return await self._inner.list_tools()

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if name in self._failing:
            return ToolOutcome(is_error=True, text=SIMULATED_OUTAGE)
        return await self._inner.call(name, arguments)


@dataclass(frozen=True)
class RunRecord:
    case_id: str
    repeat: int
    status: str
    bucket: str
    failures: tuple[str, ...]
    turns: int
    tool_calls: tuple[str, ...]
    usage: TokenUsage
    cost_usd: float | None
    seconds: float
    answer: str | None
    log_path: str


async def run_once(
    case: Case, repeat: int, model: ModelClient, model_name: str, database: Path, runs_dir: Path
) -> RunRecord:
    started = time.perf_counter()

    def wrap(executor: ToolExecutor) -> ToolExecutor:
        return FailingTools(executor, case.failing_tools) if case.failing_tools else executor

    result, log_path = await ask(
        case.question, model, database, case.max_turns or 8, runs_dir, wrap_tools=wrap
    )
    graded = grade(case, result)
    return RunRecord(
        case_id=case.id,
        repeat=repeat,
        status=result.status,
        bucket=graded.bucket,
        failures=graded.failures,
        turns=result.turns,
        tool_calls=tuple(r.call.label() for r in result.tool_calls),
        usage=result.usage,
        cost_usd=cost_usd(result.usage, model_name),
        seconds=round(time.perf_counter() - started, 1),
        answer=result.answer or result.draft_answer,
        log_path=log_path.name,  # the file under runs/; no local paths in results
    )


async def run_all(
    cases: list[Case],
    repeats: int,
    model: ModelClient,
    model_name: str,
    database: Path,
    runs_dir: Path,
    concurrency: int = 3,
) -> list[RunRecord]:
    limiter = anyio.CapacityLimiter(concurrency)
    records: list[RunRecord] = []

    async def one(case: Case, repeat: int) -> None:
        async with limiter:
            record = await run_once(case, repeat, model, model_name, database, runs_dir)
            records.append(record)
            print(f"  {case.id} #{repeat}: {record.bucket} ({record.status})", flush=True)

    async with anyio.create_task_group() as group:
        for case in cases:
            for repeat in range(1, repeats + 1):
                group.start_soon(one, case, repeat)
    return sorted(records, key=lambda r: (r.case_id, r.repeat))


def save_records(records: list[RunRecord], path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]
    path.write_text(json.dumps({"meta": meta, "runs": rows}, indent=2), encoding="utf-8")


def outcome_summary(records: list[RunRecord]) -> str:
    counts = Counter(r.bucket if r.bucket != "unexpected_status" else r.status for r in records)
    return ", ".join(f"{name} x{n}" for name, n in counts.most_common())
