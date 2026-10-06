"""Run Agent A end to end (settings, tool server, loop, run log) and render the result.

Shared by the command line and the evaluation script.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from finance_ops.agent.audit import JsonlRunLog
from finance_ops.agent.executor import ToolExecutor, local_server
from finance_ops.agent.loop import DEFAULT_MAX_TURNS, run_agent
from finance_ops.agent.model import DEFAULT_BASE_URL, DEFAULT_MODEL, ClaudeModel, ModelClient
from finance_ops.agent.types import RunResult

RUNS_DIR = Path("runs")


@dataclass(frozen=True)
class AgentSettings:
    api_key: str
    model: str
    base_url: str

    @classmethod
    def from_env(cls) -> "AgentSettings":
        """Read settings from the environment (load .env first). The key may be empty."""
        return cls(
            api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            model=os.environ.get("FINANCE_OPS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            # Deliberately not ANTHROPIC_BASE_URL: tools like Claude Code set that for themselves.
            base_url=os.environ.get("FINANCE_OPS_ANTHROPIC_BASE_URL", DEFAULT_BASE_URL),
        )

    def model_client(self) -> ClaudeModel:
        return ClaudeModel(self.api_key, self.model, self.base_url)


def new_run_log(runs_dir: Path = RUNS_DIR) -> tuple[str, JsonlRunLog]:
    run_id = uuid4().hex[:12]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return run_id, JsonlRunLog(runs_dir / f"{stamp}-{run_id}.jsonl")


async def ask(
    question: str,
    model: ModelClient,
    database: Path,
    max_turns: int = DEFAULT_MAX_TURNS,
    runs_dir: Path = RUNS_DIR,
    wrap_tools: Callable[[ToolExecutor], ToolExecutor] | None = None,
) -> tuple[RunResult, Path]:
    """Start the tool server, run the loop once, and return the result and its log path.

    wrap_tools lets the evaluation wrap the executor, for example to make a tool fail.
    """
    run_id, log = new_run_log(runs_dir)
    async with local_server(database) as executor:
        tools = wrap_tools(executor) if wrap_tools else executor
        result = await run_agent(
            question, model=model, tools=tools, max_turns=max_turns, log=log, run_id=run_id
        )
    return result, log.path


def render(result: RunResult, log_path: Path, trace: bool = False) -> str:
    lines = [_headline(result), ""]
    if trace:
        lines += [f"  turn {r.turn}: {r.call.label()} -> {r.status}" for r in result.tool_calls]
        lines.append("")
    for warning in result.data_warnings:
        lines.append(f"Data warning: {warning}")
    for error in result.tool_errors:
        lines.append(f"Tool error: {error}")
    usage = result.usage
    lines.append(
        f"[{result.status} | {result.turns} turns | {len(result.tool_calls)} tool calls | "
        f"{usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens:,} input / "
        f"{usage.output_tokens:,} output tokens | log: {log_path}]"
    )
    return "\n".join(lines)


def _headline(result: RunResult) -> str:
    if result.status in ("answered", "answered_with_data_warnings"):
        return result.answer or ""
    if result.status == "tool_error":
        return f"{result.answer}\n\nWarning: a tool failed, so this answer may be incomplete."
    if result.status == "blocked_unverified_figures":
        figures = ", ".join(result.unverified_figures)
        return (
            f"Answer withheld: it contained figures that no tool returned ({figures}). "
            "The draft is in the run log."
        )
    if result.status == "step_cap_reached":
        pending = "; ".join(result.unresolved)
        return f"Stopped after {result.turns} turns without an answer. Not resolved: {pending}."
    return f"The model call failed: {result.error}"
