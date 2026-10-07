#!/usr/bin/env bash
# Smoke-test a running MCP server over HTTP.
#
#   scripts/smoke_test.sh http://localhost:8080 "$MCP_AUTH_TOKEN"
#
# Checks: health endpoint, 401 without the token, a real tool call with it.
# Used by CI against the Docker image, and works against any deployment.
set -euo pipefail

BASE_URL="${1:?usage: smoke_test.sh BASE_URL TOKEN}"
TOKEN="${2:?usage: smoke_test.sh BASE_URL TOKEN}"
# SMOKE_RESOLVE=host:443:ip pins the address (used by tunnel.sh to bypass a stale DNS cache).
RESOLVE=()
[[ -n "${SMOKE_RESOLVE:-}" ]] && RESOLVE=(--resolve "$SMOKE_RESOLVE")
HEADERS=(
  -H "Accept: application/json, text/event-stream"
  -H "Content-Type: application/json"
  -H "MCP-Protocol-Version: 2025-06-18"
)
LIST_TOOLS='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
CALL_TOOL='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_overdue_invoices","arguments":{"min_days_overdue":60}}}'

echo "1. Health check"
curl -fsS ${RESOLVE[@]+"${RESOLVE[@]}"} "$BASE_URL/healthz"
echo

echo "2. Request without the token is rejected"
code=$(curl -s ${RESOLVE[@]+"${RESOLVE[@]}"} -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/mcp" "${HEADERS[@]}" -d "$LIST_TOOLS")
[[ "$code" == "401" ]] || { echo "expected 401, got $code"; exit 1; }
echo "401"

echo "3. Tool call with the token"
response=$(curl -fsS ${RESOLVE[@]+"${RESOLVE[@]}"} -X POST "$BASE_URL/mcp" "${HEADERS[@]}" \
  -H "Authorization: Bearer $TOKEN" -d "$CALL_TOOL")
python3 - "$response" <<'PY'
import json
import sys

result = json.loads(sys.argv[1])["result"]["structuredContent"]
assert result["status"] == "ok", result
data = result["data"]
assert data["invoice_count"] == 4, data
total = data["total_in_reporting_currency"]
print(f"ok: {data['invoice_count']} invoices over 60 days, {total['amount']} {total['currency']}")
PY
echo "Smoke test passed"
