#!/usr/bin/env bash
# Expose the local MCP server to ElevenLabs through a temporary Cloudflare quick tunnel.
#
#   scripts/tunnel.sh            (make tunnel)      server + tunnel
#   VOICE=1 scripts/tunnel.sh    (make voice-live)  ...and point the voice agent at it
#
# Starts the server over HTTP on localhost, opens a tunnel, prints the public
# https://<random>.trycloudflare.com URL and smoke-tests it. With VOICE=1 it then
# registers that URL with ElevenLabs and points the agent at it. Ctrl+C stops
# everything. Quick tunnels are temporary: they can expire within hours, and the
# URL changes every time, so run this again before a demo.
# The server's audit log (one line per tool call) streams here while it runs.
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN=$(grep -E '^MCP_AUTH_TOKEN=' .env 2>/dev/null | cut -d= -f2- || true)
[[ -n "$TOKEN" ]] || { echo "Set MCP_AUTH_TOKEN in .env first."; exit 1; }
command -v cloudflared >/dev/null || { echo "cloudflared is not installed."; exit 1; }
PORT="${PORT:-8080}"
METRICS="localhost:20241"

MCP_AUTH_TOKEN="$TOKEN" PYTHONPATH=src .venv/bin/python -m finance_ops.server \
  --transport http --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
CLOUDFLARED_PID=""
trap 'kill "$SERVER_PID" $CLOUDFLARED_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 30); do
  curl -fsS "http://localhost:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
echo "MCP server is up on localhost:$PORT. Opening the tunnel..."

# Rewrite the Host header to localhost so the server's DNS-rebinding protection,
# which only accepts localhost, stays switched on behind the tunnel.
cloudflared tunnel --no-autoupdate --metrics "$METRICS" --loglevel warn \
  --url "http://localhost:$PORT" --http-host-header "localhost:$PORT" &
CLOUDFLARED_PID=$!

HOST=""
for _ in $(seq 1 60); do
  HOST=$(curl -s "http://$METRICS/quicktunnel" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('hostname',''))" 2>/dev/null || true)
  [[ -n "$HOST" ]] && break
  sleep 1
done
[[ -n "$HOST" ]] || { echo "The tunnel did not come up."; exit 1; }
URL="https://$HOST"
# Ask public DNS, as ElevenLabs will: asking the local resolver too early makes macOS
# cache "no such host" for a while, even after the name exists.
IP=""
for _ in $(seq 1 60); do
  IP=$(dig +short @1.1.1.1 "$HOST" | grep -E '^[0-9.]+$' | head -1 || true)
  [[ -n "$IP" ]] && break
  sleep 2
done
[[ -n "$IP" ]] || { echo "Public DNS never resolved $HOST."; exit 1; }
echo "Public URL: $URL"
SMOKE_RESOLVE="$HOST:443:$IP" scripts/smoke_test.sh "$URL" "$TOKEN"

if [[ "${VOICE:-}" == "1" ]]; then
  PYTHONPATH=src .venv/bin/python -m finance_ops.voice --mcp-url "$URL" --apply
fi
echo "Running. Ctrl+C stops the server and the tunnel."
wait "$CLOUDFLARED_PID"
