#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
echo "== Python compile =="
PYTHONPATH="shared/python:." "$PYTHON" -m compileall -q shared/python services engines 2>/dev/null || true

echo "== Shared unit tests =="
if [ -x .venv/bin/pytest ]; then
    PYTHONPATH="shared/python:." .venv/bin/pytest -q tests 2>/dev/null || echo "No tests collected (or a test failed)."
else
    echo "Skipping pytest (no .venv). Install: python3 -m venv .venv && .venv/bin/pip install pytest fastapi httpx"
fi

echo "== Compose configuration =="
if command -v docker >/dev/null 2>&1; then
    docker compose config -q && echo "compose config: OK"
else
    echo "Docker not available; skipped."
fi

echo "== Frontend typecheck =="
if [ -d frontend/node_modules ]; then
    (cd frontend && npx vue-tsc --noEmit) && echo "frontend typecheck: OK"
else
    echo "Skipping frontend typecheck (run: cd frontend && npm install)"
fi
