"""Agent A's orchestration loop: model and tools, written by hand.

The loop, not the model, decides how a run ended:
- if any tool failed, the run is "tool_error", whatever the model's answer says;
- if the answer contains a figure no tool returned, the answer is withheld;
- if the step cap is reached, the run stops and lists what it did not resolve;
- partial or stale data is attached to the result as warnings, whether or not
  the model mentions it.

Before the first model turn the loop calls get_data_status itself, so the model
starts knowing today's date and which feeds are behind.
"""

import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from finance_ops.agent.audit import NullRunLog, RunLog
from finance_ops.agent.executor import ToolExecutor
from finance_ops.agent.grounding import unverified_figures
from finance_ops.agent.model import ModelClient, ModelError
from finance_ops.agent.prompts import build_system_prompt
from finance_ops.agent.types import (
    ModelTurn,
    RunResult,
    RunStatus,
    TokenUsage,
    ToolCall,
    ToolCallRecord,
    ToolOutcome,
)

DEFAULT_MAX_TURNS = 8
STATUS_TOOL = "get_data_status"
FINAL_STOP_REASONS = frozenset({"end_turn", "stop_sequence"})
DATA_QUALITY_STATUSES = frozenset({"partial", "stale"})


class _Run:
    """Mutable state for one run. Only run_agent creates one; it never escapes."""

    def __init__(self, question: str, tools: ToolExecutor, log: RunLog, run_id: str) -> None:
        self.question = question
        self.tools = tools
        self.log = log
        self.run_id = run_id
        self.sources: list[str] = [question]  # every text a figure may legitimately come from
        self.records: list[ToolCallRecord] = []
        self.data_warnings: list[str] = []
        self.tool_errors: list[str] = []
        self.usage = TokenUsage()
        self.turns = 0

    async def execute(self, call: ToolCall, turn: int) -> ToolOutcome:
        started = time.perf_counter()
        try:
            outcome = await self.tools.call(call.name, call.arguments)
        except Exception as exc:  # any executor failure becomes a tool error, never a crash
            outcome = ToolOutcome(is_error=True, text=f"Tool call failed: {type(exc).__name__}")
        duration = round((time.perf_counter() - started) * 1000, 1)
        record = ToolCallRecord(turn, call, outcome.status, outcome.is_error, duration)
        self.records.append(record)
        self.sources.append(outcome.text)
        if outcome.is_error:
            self.tool_errors.append(f"{call.label()}: {outcome.text[:200]}")
        elif outcome.status in DATA_QUALITY_STATUSES and outcome.payload:
            self.data_warnings.append(
                f"{call.label()}: {outcome.status}: {outcome.payload.get('message')}"
            )
        self.log.event(
            "tool_call",
            turn=turn,
            tool=call.name,
            arguments=call.arguments,
            status=outcome.status,
            is_error=outcome.is_error,
            duration_ms=duration,
        )
        return outcome

    def finish(self, status: RunStatus, answer: str | None = None, **extra: Any) -> RunResult:
        result = RunResult(
            run_id=self.run_id,
            question=self.question,
            status=status,
            answer=answer,
            draft_answer=extra.pop("draft_answer", answer),
            turns=self.turns,
            tool_calls=tuple(self.records),
            data_warnings=tuple(self.data_warnings),
            tool_errors=tuple(self.tool_errors),
            usage=self.usage,
            **extra,
        )
        self.log.event(
            "run_finished",
            status=status,
            answer=result.answer,
            draft_answer=result.draft_answer,
            unresolved=result.unresolved,
            unverified_figures=result.unverified_figures,
            data_warnings=result.data_warnings,
            tool_errors=result.tool_errors,
            usage=asdict(result.usage),
            error=result.error,
        )
        return result

    def judge_answer(self, text: str) -> RunResult:
        if not text:
            return self.finish("model_error", error="The model returned an empty answer.")
        unverified = tuple(unverified_figures(text, self.sources))
        if unverified:
            return self.finish(
                "blocked_unverified_figures", None, draft_answer=text, unverified_figures=unverified
            )
        if self.tool_errors:
            return self.finish("tool_error", text)
        if self.data_warnings:
            return self.finish("answered_with_data_warnings", text)
        return self.finish("answered", text)


async def run_agent(
    question: str,
    *,
    model: ModelClient,
    tools: ToolExecutor,
    max_turns: int = DEFAULT_MAX_TURNS,
    log: RunLog | None = None,
    run_id: str | None = None,
) -> RunResult:
    if max_turns < 1:
        raise ValueError("max_turns must be at least 1")
    run = _Run(question, tools, log or NullRunLog(), run_id or uuid4().hex[:12])
    run.log.event("run_started", run_id=run.run_id, question=question, max_turns=max_turns)
    specs = await tools.list_tools()
    status = await run.execute(ToolCall("orchestrator-0", STATUS_TOOL, {}), turn=0)
    system = build_system_prompt(status.payload or {})
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

    for turn in range(1, max_turns + 1):
        run.turns = turn
        try:
            reply = await model.complete(system, messages, specs)
        except ModelError as exc:
            return run.finish("model_error", error=str(exc))
        run.usage += reply.usage
        _log_turn(run.log, turn, reply)
        if not reply.tool_calls:
            if reply.stop_reason not in FINAL_STOP_REASONS:
                return run.finish(
                    "model_error",
                    draft_answer=reply.text or None,
                    error=f"The model stopped with reason {reply.stop_reason!r}.",
                )
            return run.judge_answer(reply.text)
        if turn == max_turns:
            pending = tuple(c.label() for c in reply.tool_calls)
            return run.finish("step_cap_reached", unresolved=pending)
        messages.append({"role": "assistant", "content": list(reply.content)})
        results = []
        for call in reply.tool_calls:
            outcome = await run.execute(call, turn)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": outcome.text,
                    "is_error": outcome.is_error,
                }
            )
        messages.append({"role": "user", "content": results})
    raise AssertionError("unreachable: the last turn always returns")


def _log_turn(log: RunLog, turn: int, reply: ModelTurn) -> None:
    log.event(
        "model_turn",
        turn=turn,
        stop_reason=reply.stop_reason,
        tool_calls=[c.label() for c in reply.tool_calls],
        text=reply.text or None,
        usage=asdict(reply.usage),
    )
