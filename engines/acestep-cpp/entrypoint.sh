#!/usr/bin/env bash
set -euo pipefail

DEVICE="${ACESTEP_CPP_DEVICE:-CPU}"
MODELS_DIR="${ACESTEP_CPP_MODELS_DIR:-/data/models/acestep}"
PORT="${ACESTEP_CPP_PORT:-8085}"
MAX_BATCH="${ACESTEP_CPP_MAX_BATCH:-1}"

mkdir -p "${MODELS_DIR}"
if [ ! -w "${MODELS_DIR}" ]; then
    echo "[acestep] ERROR: ${MODELS_DIR} is not writable by uid $(id -u)." >&2
    echo "[acestep] Give the container user write access to the model volume or mount a pre-populated directory." >&2
    exit 4
fi

/opt/acestep/download-models.sh

ARGS=(--models "${MODELS_DIR}" --host 0.0.0.0 --port "${PORT}" --device "${DEVICE}" --max-batch "${MAX_BATCH}")

if [ "${ACESTEP_CPP_KEEP_LOADED:-false}" = "true" ]; then
    ARGS+=(--keep-loaded)
fi
if [ "${ACESTEP_CPP_CLAMP_FP16:-false}" = "true" ]; then
    ARGS+=(--clamp-fp16)
fi
if [ "${ACESTEP_CPP_NO_FA:-false}" = "true" ]; then
    ARGS+=(--no-fa)
fi
if [ -n "${ACESTEP_CPP_EXTRA_ARGS:-}" ]; then
    # Simple flag-only extras; deliberately no shell evaluation.
    read -r -a EXTRA <<<"${ACESTEP_CPP_EXTRA_ARGS}"
    ARGS+=("${EXTRA[@]}")
fi

echo "[acestep] Starting Open Studio ACE-Step 1.5 GGUF engine"
echo "[acestep] device=${DEVICE} models=${MODELS_DIR} port=${PORT} max-batch=${MAX_BATCH}"
echo "[acestep] strict per-stage model eviction: $([ "${ACESTEP_CPP_KEEP_LOADED:-false}" = "true" ] && echo off || echo on)"

exec /opt/acestep/ace-server "${ARGS[@]}"
