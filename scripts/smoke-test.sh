#!/usr/bin/env bash
set -euo pipefail

BASE="${OPENSTUDIO_URL:-http://127.0.0.1:8090}"
API="${OPENSTUDIO_API:-http://127.0.0.1:8091/api}"
COOKIE="$(mktemp)"
trap 'rm -f "$COOKIE"' EXIT

echo "== public health =="
curl -fsS "$API/health" | python3 -m json.tool

STATUS="$(curl -fsS "$API/auth/status")"
echo "$STATUS" | python3 -m json.tool

if [ -n "${OPENSTUDIO_PASSWORD:-}" ]; then
    echo "== login =="
    curl -fsS -c "$COOKIE" -H 'Content-Type: application/json' \
        -d "{\"password\":\"${OPENSTUDIO_PASSWORD}\"}" "$API/auth/login" >/dev/null
    echo "== authenticated status =="
    curl -fsS -b "$COOKIE" "$API/status" > /tmp/openstudio-smoke-status.json
    python3 -c '
import json
data=json.load(open("/tmp/openstudio-smoke-status.json"))
print("services: %s/%s online" % (data["online"], data["total"]))
for s in data["services"]:
    print("  %s %-12s %s" % ("OK " if s["online"] else "OFF", s["name"], s.get("version") or s.get("detail") or ""))
print("storage free: %s" % data["storage"]["free_label"])
'
    echo "== files =="
    curl -fsS -b "$COOKIE" "$API/files/list" | python3 -c "import json,sys; d=json.load(sys.stdin); print('files:', d.get('count', len(d.get('items',[]))))"
    echo "== jobs =="
    curl -fsS -b "$COOKIE" "$API/jobs?limit=5" | python3 -c "import json,sys; d=json.load(sys.stdin); print('jobs:', d.get('total'))"
else
    echo "Set OPENSTUDIO_PASSWORD to run authenticated smoke checks."
fi

echo "== frontend =="
curl -fsS -o /dev/null -w "frontend HTTP %{http_code}\n" "$BASE/"
echo "Smoke test complete."
