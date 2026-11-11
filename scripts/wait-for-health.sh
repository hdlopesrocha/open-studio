#!/usr/bin/env bash
set -euo pipefail

PORT="${OPENSTUDIO_PORT:-8090}"
GATEWAY_PORT="${GATEWAY_PORT:-8091}"
DEADLINE=$((SECONDS + ${WAIT_SECONDS:-600}))
echo "Waiting for Open Studio (frontend :$PORT, gateway :$GATEWAY_PORT)..."
while [ $SECONDS -lt $DEADLINE ]; do
    if curl -fsS "http://127.0.0.1:${GATEWAY_PORT}/api/health" >/dev/null 2>&1; then
        if curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
            echo "Open Studio is healthy."
            curl -fsS "http://127.0.0.1:${GATEWAY_PORT}/api/health" | python3 -m json.tool 2>/dev/null || true
            exit 0
        fi
    fi
    printf "."
    sleep 3
done
echo ""
echo "Timed out. Inspect: docker compose ps && docker compose logs --tail=100" >&2
exit 1
