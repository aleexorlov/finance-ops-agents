#!/usr/bin/env bash
# Expose the local MCP server to ElevenLabs through a temporary Cloudflare quick tunnel.
#
#   scripts/tunnel.sh        (or: make tunnel)
#
# Starts the server over HTTP on localhost, then opens a tunnel and prints a public
# https://<random>.trycloudflare.com URL. Ctrl+C stops both. Nothing persists: the
# URL changes every time, and nothing is reachable once this stops.
# The server's audit log (one line per tool call) streams here while it runs.
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN=$(grep -E '^MCP_AUTH_TOKEN=' .env 2>/dev/null | cut -d= -f2- || true)
[[ -n "$TOKEN" ]] || { echo "Set MCP_AUTH_TOKEN in .env first."; exit 1; }
command -v cloudflared >/dev/null || { echo "cloudflared is not installed."; exit 1; }
PORT="${PORT:-8080}"

MCP_AUTH_TOKEN="$TOKEN" PYTHONPATH=src .venv/bin/python -m finance_ops.server \
  --transport http --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS "http://localhost:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
echo "MCP server is up on localhost:$PORT. Opening the tunnel..."

# Rewrite the Host header to localhost so the server's DNS-rebinding protection,
# which only accepts localhost, stays switched on behind the tunnel.
cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" \
  --http-host-header "localhost:$PORT"
