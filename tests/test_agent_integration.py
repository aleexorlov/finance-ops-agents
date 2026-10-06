"""The loop against the real tool server over stdio, with a scripted model.

Exercises the subprocess, the MCP client and the JSON round trip without an API key.
"""

import json
from pathlib import Path

import anyio
import pytest
from fakes import ScriptedModel, final_turn, tool_turn
from mcp.client.stdio import get_default_environment

from finance_ops.agent.executor import local_server, server_parameters
from finance_ops.agent.loop import run_agent
from finance_ops.agent.model import DEFAULT_BASE_URL
from finance_ops.agent.runner import AgentSettings
from finance_ops.agent.types import ToolCall

RECONCILE = ToolCall("c1", "reconcile_invoice", {"invoice_id": "INV-202609-1007"})


def run_against_server(db_file: Path, model: ScriptedModel):
    async def go():
        async with local_server(db_file) as tools:
            return await run_agent("Is INV-202609-1007 right?", model=model, tools=tools)

    return anyio.run(go)


def test_answer_grounded_in_real_tool_output_is_answered(db_file: Path) -> None:
    model = ScriptedModel(
        tool_turn(RECONCILE),
        final_turn("INV-202609-1007 is overbilled by £1,637.36: it should be £999.00."),
    )
    result = run_against_server(db_file, model)
    assert result.status == "answered", result
    assert [r.status for r in result.tool_calls] == ["ok", "ok"]


def test_figure_not_in_real_tool_output_is_withheld(db_file: Path) -> None:
    model = ScriptedModel(tool_turn(RECONCILE), final_turn("It is overbilled by £1,600.00."))
    result = run_against_server(db_file, model)
    assert result.status == "blocked_unverified_figures"
    assert result.unverified_figures == ("£1,600.00",)


def test_tool_server_process_does_not_inherit_the_api_key(
    db_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-should-not-leak")
    params = server_parameters(db_file)
    child_env = get_default_environment() | (params.env or {})  # what the SDK launches with
    assert "ANTHROPIC_API_KEY" not in child_env
    assert child_env["FINANCE_OPS_DB"] == str(db_file.resolve())


def test_settings_ignore_another_tools_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9/somebody-elses-proxy")
    monkeypatch.delenv("FINANCE_OPS_ANTHROPIC_BASE_URL", raising=False)
    assert AgentSettings.from_env().base_url == DEFAULT_BASE_URL


def test_quoting_the_overage_rate_and_its_unit_is_grounded(db_file: Path) -> None:
    # Run 1 of the evaluation withheld 11 correct answers over this sentence: the
    # tools gave the rate but the "1,000" only appeared in a field name.
    from finance_ops.agent.grounding import unverified_figures
    from finance_ops.server.db import Database
    from finance_ops.server.tools import FinanceTools

    tools = FinanceTools(Database(db_file))
    sources = [
        json.dumps(tools.get_usage("ACC-1010", "2026-09")),
        json.dumps(tools.get_account("ACC-1005")),
        json.dumps(tools.get_invoice("INV-202609-1007")),
        json.dumps(tools.reconcile_invoice("INV-202609-1007")),
    ]
    answer = (
        "Overage is GBP 0.80 per 1,000 credits; Enterprise is EUR 0.20 per 1,000 credits; "
        "the invoice applied 0.50 per 1,000 instead of 0.30 per 1,000."
    )
    assert unverified_figures(answer, sources) == []
