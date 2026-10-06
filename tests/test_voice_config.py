"""Agent B's configuration and the requests built from it. No network calls."""

import json
from pathlib import Path

import pytest

from finance_ops.voice.elevenlabs import (
    REDACTED,
    agent_request,
    load_config,
    mcp_endpoint,
    mcp_server_request,
    redact,
    secret_request,
)

VOICE_DIR = Path(__file__).resolve().parents[1] / "voice_agent"
CONFIG = load_config(VOICE_DIR)


def test_config_loads_and_uses_the_same_model_family_as_agent_a() -> None:
    assert CONFIG.llm == "claude-sonnet-5-5"
    assert "Never calculate" in CONFIG.prompt
    assert "Never choose for them" in CONFIG.prompt


def test_mcp_endpoint_requires_https_and_adds_the_path() -> None:
    assert (
        mcp_endpoint("https://example.trycloudflare.com/")
        == "https://example.trycloudflare.com/mcp"
    )
    assert mcp_endpoint("https://run.app/mcp") == "https://run.app/mcp"
    with pytest.raises(ValueError, match="HTTPS"):
        mcp_endpoint("http://localhost:8080")


def test_server_registration_references_the_secret_never_the_token() -> None:
    request = mcp_server_request("https://h/mcp", "sec_123", CONFIG.approval_policy)
    config = request.body["config"]
    assert config["secret_token"] == {"secret_id": "sec_123"}
    assert config["transport"] == "STREAMABLE_HTTP"
    assert config["approval_policy"] == "auto_approve_all"


def test_agent_points_at_the_mcp_server_and_updates_when_an_id_is_known() -> None:
    created = agent_request(CONFIG, "mcp_1", None)
    prompt = created.body["conversation_config"]["agent"]["prompt"]
    assert (created.method, created.path) == ("POST", "/v1/convai/agents/create")
    assert prompt["mcp_server_ids"] == ["mcp_1"]
    updated = agent_request(CONFIG, "mcp_1", "agent_9")
    assert (updated.method, updated.path) == ("PATCH", "/v1/convai/agents/agent_9")


def test_dry_run_output_never_contains_the_token() -> None:
    printed = json.dumps(redact(secret_request("super-secret-token")))
    assert "super-secret-token" not in printed
    assert REDACTED in printed
