"""Scripted model, fake tools and log used by the loop and integration tests."""

import json
from typing import Any

from finance_ops.agent.types import ModelTurn, TokenUsage, ToolCall, ToolOutcome, ToolSpec

DATA_STATUS = {
    "status": "ok",
    "message": None,
    "as_of": "2026-10-05T06:00:00Z",
    "warnings": ["The usage feed has data only through 2026-10-01."],
    "data": {"today": "2026-10-05", "reporting_currency": "GBP"},
}


def envelope(status: str = "ok", message: str | None = None, **data: Any) -> ToolOutcome:
    payload = {"status": status, "message": message, "as_of": "x", "warnings": [], "data": data}
    return ToolOutcome(is_error=status == "error", text=json.dumps(payload), payload=payload)


def tool_turn(*calls: ToolCall) -> ModelTurn:
    content = tuple(
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls
    )
    return ModelTurn("", calls, "tool_use", TokenUsage(100, 20), content)


def final_turn(text: str, stop_reason: str = "end_turn") -> ModelTurn:
    return ModelTurn(text, (), stop_reason, TokenUsage(100, 40), ({"type": "text", "text": text},))


GET_INVOICE = ToolCall("call-1", "get_invoice", {"invoice_id": "INV-202608-1007"})


class ScriptedModel:
    def __init__(self, *turns: ModelTurn | Exception) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec]
    ) -> ModelTurn:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        if isinstance(turn, Exception):
            raise turn
        return turn


class FakeTools:
    def __init__(self, **responses: ToolOutcome | Exception) -> None:
        status = ToolOutcome(False, json.dumps(DATA_STATUS), DATA_STATUS)
        self.responses: dict[str, ToolOutcome | Exception] = {
            "get_data_status": status,
            **responses,
        }
        self.called: list[str] = []

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec(name, "", {"type": "object"}) for name in self.responses]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.called.append(name)
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return response


class ListLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def event(self, kind: str, **fields: Any) -> None:
        self.events.append({"event": kind, **fields})
