"""Plain data passed between the loop, the model adapter and the tool executor.

Kept free of SDK types so the loop can be tested with scripted fakes.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

RunStatus = Literal[
    "answered",  # final answer, every figure verified, no tool errors, data complete
    "answered_with_data_warnings",  # as above, but some data was partial or stale
    "tool_error",  # a tool failed; the answer is shown, labelled as possibly incomplete
    "blocked_unverified_figures",  # the answer contained figures no tool returned; withheld
    "step_cap_reached",  # stopped before an answer; unresolved work is listed
    "model_error",  # the model API failed or returned an unusable response
]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def label(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items())
        return f"{self.name}({args})"


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool returned. `text` is exactly what the model is shown."""

    is_error: bool
    text: str
    payload: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        if self.payload is not None:
            return str(self.payload.get("status", "error"))
        return "error" if self.is_error else "ok"


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class ModelTurn:
    """One model response, already translated out of the SDK's types."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str
    usage: TokenUsage
    content: tuple[dict[str, Any], ...]  # assistant content blocks, replayed in history


@dataclass(frozen=True)
class ToolCallRecord:
    turn: int
    call: ToolCall
    status: str
    is_error: bool
    duration_ms: float


@dataclass(frozen=True)
class RunResult:
    run_id: str
    question: str
    status: RunStatus
    answer: str | None  # what may be shown to the user; None when withheld
    draft_answer: str | None  # the model's final text, kept for the log even when withheld
    turns: int
    tool_calls: tuple[ToolCallRecord, ...] = ()
    unresolved: tuple[str, ...] = ()
    data_warnings: tuple[str, ...] = ()
    tool_errors: tuple[str, ...] = ()
    unverified_figures: tuple[str, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    error: str | None = None
