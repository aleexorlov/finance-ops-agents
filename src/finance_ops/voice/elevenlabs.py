"""Agent B on ElevenAgents, kept as configuration in this repo.

voice_agent/agent.json and voice_agent/system_prompt.md are the source of truth.
This module turns them into the three ElevenLabs API calls that set the agent up:

1. store the MCP server's bearer token as a workspace secret,
2. register the MCP server by URL, referencing that secret (never the raw token),
3. create the agent, or update it if ELEVENLABS_AGENT_ID is set, pointing at the server.

Nothing is sent unless --apply is given; without it the requests are printed with
the token redacted.
"""

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_BASE = "https://api.elevenlabs.io"
SECRET_PREFIX = "finance-ops-mcp-token"
MCP_SERVER_NAME = "finance-ops (read-only billing tools)"
MCP_SERVER_DESCRIPTION = (
    "Read-only tools over a synthetic billing dataset: accounts, usage, invoices, "
    "reconciliation and overdue balances. No tool can change data."
)
REDACTED = "<redacted>"


@dataclass(frozen=True)
class VoiceAgentConfig:
    name: str
    llm: str
    language: str
    first_message: str
    max_duration_seconds: int
    approval_policy: str
    tags: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    body: dict[str, Any]


def load_config(directory: Path) -> VoiceAgentConfig:
    raw = json.loads((directory / "agent.json").read_text(encoding="utf-8"))
    prompt = (directory / "system_prompt.md").read_text(encoding="utf-8").strip()
    return VoiceAgentConfig(**{**raw, "tags": tuple(raw.get("tags", ())), "prompt": prompt})


def mcp_endpoint(base_url: str) -> str:
    """The server's MCP endpoint from its base URL. ElevenLabs requires HTTPS."""
    url = base_url.rstrip("/")
    if not url.startswith("https://"):
        raise ValueError(f"ElevenLabs needs an HTTPS URL for the MCP server; got {base_url!r}.")
    return url if url.endswith("/mcp") else f"{url}/mcp"


def secret_name(token: str) -> str:
    """Name the secret after a fingerprint of the token, so a rotated token gets a new
    secret instead of silently reusing the old one. The fingerprint reveals nothing."""
    return f"{SECRET_PREFIX}-{hashlib.sha256(token.encode()).hexdigest()[:8]}"


def secret_request(token: str) -> Request:
    return Request(
        "POST", "/v1/convai/secrets", {"type": "new", "name": secret_name(token), "value": token}
    )


def mcp_server_request(url: str, secret_id: str, approval_policy: str) -> Request:
    return Request(
        "POST",
        "/v1/convai/mcp-servers",
        {
            "config": {
                "url": url,
                "name": MCP_SERVER_NAME,
                "description": MCP_SERVER_DESCRIPTION,
                "transport": "STREAMABLE_HTTP",
                # Every tool is read-only, so calls need no human approval. A tool that
                # could change data would get "require_approval_per_tool" instead.
                "approval_policy": approval_policy,
                "secret_token": {"secret_id": secret_id},
            }
        },
    )


def agent_request(config: VoiceAgentConfig, mcp_server_id: str, agent_id: str | None) -> Request:
    body = {
        "name": config.name,
        "tags": list(config.tags),
        "conversation_config": {
            "agent": {
                "first_message": config.first_message,
                "language": config.language,
                "prompt": {
                    "prompt": config.prompt,
                    "llm": config.llm,
                    "mcp_server_ids": [mcp_server_id],
                },
            },
            "conversation": {"max_duration_seconds": config.max_duration_seconds},
        },
    }
    if agent_id:
        return Request("PATCH", f"/v1/convai/agents/{agent_id}", body)
    return Request("POST", "/v1/convai/agents/create", body)


class ElevenLabsClient:
    def __init__(self, api_key: str, base: str = API_BASE) -> None:
        self._api_key = api_key
        self._base = base

    def find_secret_id(self, name: str) -> str | None:
        """The ID of an existing workspace secret with this name, so re-runs reuse it."""
        listing = self.send(Request("GET", "/v1/convai/secrets", {}))
        matches = [s["secret_id"] for s in listing.get("secrets", []) if s.get("name") == name]
        return matches[0] if matches else None

    def server_url(self, server_id: str) -> str | None:
        """The URL an already registered MCP server points at."""
        server = self.send(Request("GET", f"/v1/convai/mcp-servers/{server_id}", {}))
        return server.get("config", {}).get("url")

    def send(self, request: Request) -> dict[str, Any]:
        http = urllib.request.Request(
            self._base + request.path,
            data=json.dumps(request.body).encode() if request.body else None,
            method=request.method,
            headers={"xi-api-key": self._api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(http, timeout=30) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{request.method} {request.path} -> {exc.code}: {detail}") from exc


def redact(request: Request) -> dict[str, Any]:
    body = json.loads(json.dumps(request.body))
    if "value" in body:
        body["value"] = REDACTED
    return {"method": request.method, "path": request.path, "body": body}
