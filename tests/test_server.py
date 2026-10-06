"""The MCP layer: what a client sees, the audit log, read-only access, HTTP auth."""

import json
import logging
import sqlite3
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult
from starlette.testclient import TestClient

from finance_ops.server.app import TOOL_NAMES, build_server, create_http_app
from finance_ops.server.db import Database

TOKEN = "test-token-not-a-secret"
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def test_client_sees_nine_read_only_tools_with_formats_documented(db_file: Path) -> None:
    async def list_tools() -> list:
        async with Client(build_server(db_file)) as client:
            return (await client.list_tools()).tools

    tools = anyio.run(list_tools)
    assert sorted(t.name for t in tools) == sorted(TOOL_NAMES)
    for tool in tools:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        for name, prop in tool.input_schema.get("properties", {}).items():
            assert "e.g." in prop.get("description", ""), f"{tool.name}.{name} lacks an example"


def test_tool_call_returns_the_envelope_and_is_logged(
    db_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def call() -> dict:
        async with Client(build_server(db_file)) as client:
            result = await client.call_tool("get_account", {"account_id": "ACC-1007"})
            return result.structured_content

    with caplog.at_level(logging.INFO, logger="finance_ops.audit"):
        envelope = anyio.run(call)
    assert envelope["status"] == "ok"
    [record] = [json.loads(r.message) for r in caplog.records if r.name == "finance_ops.audit"]
    assert record["tool"] == "get_account"
    assert json.loads(record["arguments"]) == {"account_id": "ACC-1007"}
    assert record["status"] == "ok"


def call_logged(
    db_file: Path, caplog: pytest.LogCaptureFixture, tool: str, arguments: dict
) -> tuple[CallToolResult, list[dict]]:
    """Call a tool through a real MCP client; return the result and the audit lines."""

    async def call() -> CallToolResult:
        async with Client(build_server(db_file)) as client:
            return await client.call_tool(tool, arguments)

    with caplog.at_level(logging.INFO, logger="finance_ops.audit"):
        result = anyio.run(call)
    lines = [json.loads(r.message) for r in caplog.records if r.name == "finance_ops.audit"]
    return result, lines


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_account", {}),  # missing argument, rejected by the schema
        ("get_account", {"account_id": 1007}),  # a number where text is expected
        ("get_usage", {"account_id": "ACC-1007", "month": "0000-01"}),  # impossible year
        ("get_overdue_invoices", {"min_days_overdue": "60"}),  # text where a number is expected
        ("get_overdue_invoices", {"min_days_overdue": True}),
    ],
)
def test_bad_arguments_get_an_invalid_input_envelope_and_are_logged(
    db_file: Path, caplog: pytest.LogCaptureFixture, tool: str, arguments: dict
) -> None:
    result, lines = call_logged(db_file, caplog, tool, arguments)
    assert result.is_error is False
    assert result.structured_content["status"] == "invalid_input"
    assert [(line["tool"], line["status"]) for line in lines] == [(tool, "invalid_input")]


def test_a_crashing_tool_returns_an_error_envelope_without_internals(
    db_file: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("finance_ops.server.queries.account", broken)
    result, lines = call_logged(db_file, caplog, "get_account", {"account_id": "ACC-1007"})
    assert result.structured_content["status"] == "error"
    assert "secret internal detail" not in json.dumps(result.structured_content)
    assert lines[-1]["status"] == "error"


def test_an_unknown_tool_is_an_error_and_is_logged(
    db_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    result, lines = call_logged(db_file, caplog, "delete_invoice", {"invoice_id": "INV-1"})
    assert result.is_error is True
    assert [(line["tool"], line["status"]) for line in lines] == [("delete_invoice", "error")]


def test_database_connection_cannot_write(db_file: Path) -> None:
    with Database(db_file).connect() as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM invoices")


def test_missing_database_fails_with_a_clear_message(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="make data"):
        Database(tmp_path / "absent.sqlite")


@pytest.fixture
def http(db_file: Path) -> TestClient:
    with TestClient(create_http_app(db_file, TOKEN, host="0.0.0.0")) as client:
        yield client


def test_http_health_check_needs_no_token(http: TestClient) -> None:
    assert http.get("/healthz").json() == {"status": "ok"}


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "", "Bearer "])
def test_http_rejects_missing_or_wrong_token(http: TestClient, authorization: str | None) -> None:
    headers = dict(MCP_HEADERS)
    if authorization is not None:
        headers["authorization"] = authorization
    assert http.post("/mcp", json=LIST_TOOLS, headers=headers).status_code == 401


@pytest.mark.parametrize("authorization", [f"Bearer {TOKEN}", f"bearer {TOKEN}", TOKEN])
def test_http_accepts_the_token_with_or_without_bearer(
    http: TestClient, authorization: str
) -> None:
    response = http.post(
        "/mcp", json=LIST_TOOLS, headers={**MCP_HEADERS, "authorization": authorization}
    )
    assert response.status_code == 200
    assert len(response.json()["result"]["tools"]) == len(TOOL_NAMES)


def test_http_app_refuses_to_start_without_a_token(db_file: Path) -> None:
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        create_http_app(db_file, "", host="0.0.0.0")


def test_http_rejects_two_authorization_headers(http: TestClient) -> None:
    headers = [(k, v) for k, v in MCP_HEADERS.items()]
    headers += [("authorization", f"Bearer {TOKEN}"), ("authorization", "Bearer other")]
    assert http.post("/mcp", json=LIST_TOOLS, headers=headers).status_code == 401


def test_http_only_get_healthz_is_open(http: TestClient) -> None:
    response = http.post("/healthz")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
