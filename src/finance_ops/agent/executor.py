"""The tool side of the loop: a small protocol, and the MCP implementation."""

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from mcp import Client, StdioServerParameters

from finance_ops.agent.types import ToolOutcome, ToolSpec


class ToolExecutor(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


class MCPToolExecutor:
    """Calls tools on a connected MCP client and turns results into ToolOutcomes."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_tools(self) -> list[ToolSpec]:
        result = await self._client.list_tools()
        return [ToolSpec(t.name, t.description or "", t.input_schema) for t in result.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        result = await self._client.call_tool(name, arguments)
        if result.is_error or result.structured_content is None:
            text = " ".join(getattr(c, "text", "") for c in result.content) or "Tool failed."
            return ToolOutcome(is_error=True, text=text)
        payload = dict(result.structured_content)
        # Compact JSON: the model reads exactly this, and every token is paid for.
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return ToolOutcome(is_error=payload.get("status") == "error", text=text, payload=payload)


def server_parameters(database: Path) -> StdioServerParameters:
    """How to start the tool server as a stdio subprocess.

    The MCP SDK merges this env over a short allow-list of variables (PATH, HOME
    and similar), so the subprocess never inherits the API key from this process.
    """
    src_dir = Path(__file__).resolve().parents[2]
    import_path = os.pathsep.join(filter(None, [str(src_dir), os.environ.get("PYTHONPATH")]))
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "finance_ops.server"],
        env={"FINANCE_OPS_DB": str(database.resolve()), "PYTHONPATH": import_path},
    )


@asynccontextmanager
async def local_server(database: Path) -> AsyncIterator[MCPToolExecutor]:
    """Start the tool server as a stdio subprocess and connect to it."""
    async with Client(server_parameters(database)) as client:
        yield MCPToolExecutor(client)
