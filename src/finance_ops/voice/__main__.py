"""Set up Agent B on ElevenAgents from voice_agent/.

    python -m finance_ops.voice --mcp-url https://<public-host>            # dry run
    python -m finance_ops.voice --mcp-url https://<public-host> --apply    # sends it

Needs ELEVENLABS_API_KEY and MCP_AUTH_TOKEN in .env. Set ELEVENLABS_AGENT_ID and
ELEVENLABS_MCP_SERVER_ID after the first run to update instead of creating again.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from finance_ops.voice.elevenlabs import (
    ElevenLabsClient,
    agent_request,
    load_config,
    mcp_endpoint,
    mcp_server_request,
    redact,
    secret_request,
)

REPO = Path(__file__).resolve().parents[3]
PLACEHOLDER_ID = "<id from the previous step>"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update the ElevenAgents voice agent.")
    parser.add_argument("--mcp-url", required=True, help="public HTTPS base URL of the MCP server")
    parser.add_argument("--apply", action="store_true", help="send the requests (default: print)")
    args = parser.parse_args()

    load_dotenv(REPO / ".env")
    config = load_config(REPO / "voice_agent")
    url = mcp_endpoint(args.mcp_url)
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    agent_id = os.environ.get("ELEVENLABS_AGENT_ID") or None
    server_id = os.environ.get("ELEVENLABS_MCP_SERVER_ID") or None
    if not token:
        sys.exit("MCP_AUTH_TOKEN is not set in .env.")

    if not args.apply:
        steps = [] if server_id else [secret_request(token)]
        if not server_id:
            steps.append(mcp_server_request(url, PLACEHOLDER_ID, config.approval_policy))
        steps.append(agent_request(config, server_id or PLACEHOLDER_ID, agent_id))
        print("Dry run. These requests would be sent (re-run with --apply):\n")
        for step in steps:
            print(json.dumps(redact(step), indent=2), "\n")
        return

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set in .env.")
    client = ElevenLabsClient(api_key)
    if not server_id:
        secret_id = client.send(secret_request(token))["secret_id"]
        server_id = client.send(mcp_server_request(url, secret_id, config.approval_policy))["id"]
        print(f"MCP server registered: ELEVENLABS_MCP_SERVER_ID={server_id}")
    result = client.send(agent_request(config, server_id, agent_id))
    agent_id = agent_id or result["agent_id"]
    print(f"Agent ready: ELEVENLABS_AGENT_ID={agent_id}")
    print("Add both IDs to .env so the next run updates rather than creates.")


if __name__ == "__main__":
    main()
