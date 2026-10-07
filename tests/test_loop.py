"""The orchestration loop with a scripted model and fake tools. No API key needed.

The model is scripted, so these tests are about the loop's own guarantees: what
it does when a tool fails, when an answer contains an unsupported figure, when
the step cap is reached, and that every call is logged.
"""

from typing import Any

import anyio
import pytest
from fakes import GET_INVOICE, FakeTools, ListLog, ScriptedModel, envelope, final_turn, tool_turn

from finance_ops.agent.loop import run_agent
from finance_ops.agent.model import ModelError
from finance_ops.agent.types import TokenUsage, ToolCall


def run(question: str, model: ScriptedModel, tools: FakeTools, **kwargs: Any):
    return anyio.run(lambda: run_agent(question, model=model, tools=tools, **kwargs))


def test_answer_with_figures_from_tools_is_answered() -> None:
    model = ScriptedModel(tool_turn(GET_INVOICE), final_turn("August's invoice was £1,355.31."))
    tools = FakeTools(get_invoice=envelope(total="1355.31"))
    result = run("What was August's invoice?", model, tools)
    assert result.status == "answered"
    assert result.answer == "August's invoice was £1,355.31."
    assert result.turns == 2
    assert [r.call.name for r in result.tool_calls] == ["get_data_status", "get_invoice"]
    assert result.usage == TokenUsage(200, 60)


def test_tool_failure_is_passed_to_the_model_and_the_run_is_not_answered() -> None:
    # The model claims success anyway; the loop must not report the run as answered.
    model = ScriptedModel(tool_turn(GET_INVOICE), final_turn("Done: the invoice is fully paid."))
    tools = FakeTools(get_invoice=ConnectionError("server went away"))
    result = run("Is the August invoice paid?", model, tools)
    assert result.status == "tool_error"
    assert result.tool_errors and "get_invoice" in result.tool_errors[0]
    [tool_result] = model.calls[1]["messages"][-1]["content"]
    assert tool_result["is_error"] is True
    assert "ConnectionError" in tool_result["content"]


def test_error_status_in_the_envelope_counts_as_a_tool_failure() -> None:
    model = ScriptedModel(tool_turn(GET_INVOICE), final_turn("All fine."))
    result = run("?", model, FakeTools(get_invoice=envelope("error", "database locked")))
    assert result.status == "tool_error"


def test_answer_with_a_figure_no_tool_returned_is_withheld() -> None:
    model = ScriptedModel(tool_turn(GET_INVOICE), final_turn("The invoice was £1,400.00."))
    result = run("?", model, FakeTools(get_invoice=envelope(total="1355.31")))
    assert result.status == "blocked_unverified_figures"
    assert result.answer is None
    assert result.draft_answer == "The invoice was £1,400.00."
    assert result.unverified_figures == ("£1,400.00",)


def test_step_cap_stops_the_run_and_lists_what_was_not_resolved() -> None:
    model = ScriptedModel(tool_turn(GET_INVOICE))  # asks for a tool every turn, forever
    tools = FakeTools(get_invoice=envelope(total="1355.31"))
    result = run("?", model, tools, max_turns=3)
    assert result.status == "step_cap_reached"
    assert result.turns == 3
    assert len(model.calls) == 3
    assert tools.called == ["get_data_status", "get_invoice", "get_invoice"]
    assert result.unresolved == ("get_invoice(invoice_id='INV-202608-1007')",)
    assert result.answer is None


def test_partial_data_is_attached_as_a_warning() -> None:
    model = ScriptedModel(
        tool_turn(ToolCall("c1", "get_usage", {"account_id": "ACC-1024", "month": "2026-09"})),
        final_turn("Usage is incomplete: 3 days missing, 1,062,985 credits recorded."),
    )
    tools = FakeTools(
        get_usage=envelope("partial", "No usage on 3 days.", credits_recorded=1062985)
    )
    result = run("?", model, tools)
    assert result.status == "answered_with_data_warnings"
    assert "No usage on 3 days." in result.data_warnings[0]


def test_model_api_failure_is_a_model_error() -> None:
    result = run("?", ScriptedModel(ModelError("overloaded")), FakeTools())
    assert (result.status, result.error) == ("model_error", "overloaded")


def test_truncated_response_is_a_model_error_not_an_answer() -> None:
    model = ScriptedModel(final_turn("The total is", stop_reason="max_tokens"))
    result = run("?", model, FakeTools())
    assert result.status == "model_error"
    assert result.answer is None


def test_data_status_is_fetched_first_and_put_in_the_system_prompt() -> None:
    model = ScriptedModel(final_turn("Nothing to report."))
    run("?", model, FakeTools())
    system = model.calls[0]["system"]
    assert "Today is 2026-10-05" in system
    assert "usage feed has data only through 2026-10-01" in system


def test_every_tool_call_and_the_outcome_are_logged() -> None:
    log = ListLog()
    model = ScriptedModel(tool_turn(GET_INVOICE), final_turn("It was £1,355.31."))
    run("?", model, FakeTools(get_invoice=envelope(total="1355.31")), log=log)
    kinds = [e["event"] for e in log.events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    assert [e["tool"] for e in log.events if e["event"] == "tool_call"] == [
        "get_data_status",
        "get_invoice",
    ]
    assert log.events[-1]["status"] == "answered"


def test_max_turns_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        run("?", ScriptedModel(final_turn("x")), FakeTools(), max_turns=0)


def test_a_tool_server_that_cannot_list_its_tools_ends_the_run_cleanly() -> None:
    class Unreachable(FakeTools):
        async def list_tools(self) -> list:
            raise ConnectionError("server did not start")

    log = ListLog()
    result = run("?", ScriptedModel(final_turn("x")), Unreachable(), log=log)
    assert result.status == "tool_error"
    assert log.events[-1]["event"] == "run_finished"
