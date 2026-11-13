#!/usr/bin/env bash
# Download the GGUF files needed by the Dockerized Open Studio ACE-Step engine.
# The download is resumable and only fetches missing files.
set -euo pipefail

MODELS_DIR="${ACESTEP_CPP_MODELS_DIR:-/data/models/acestep}"
DOWNLOAD="${ACESTEP_CPP_DOWNLOAD_MODELS:-true}"
LM_SIZE="${ACESTEP_CPP_LM_SIZE:-0.6B}"
QUANT="${ACESTEP_CPP_QUANT:-Q8_0}"
DIT_VARIANT="${ACESTEP_CPP_DIT_VARIANT:-turbo}"
HF_ENDPOINT="${ACESTEP_CPP_HF_ENDPOINT:-https://huggingface.co}"
REPO="${ACESTEP_CPP_HF_REPO:-Serveurperso/ACE-Step-1.5-GGUF}"
BASE_URL="${HF_ENDPOINT%/}/${REPO}/resolve/main"

# Small LM + text encoder only publish BF16 / Q8_0. The DiT supports Q4/Q5/Q6/Q8/BF16.
case "${LM_SIZE}" in
    0.6B|1.7B) LM_FILE="acestep-5Hz-lm-${LM_SIZE}-Q8_0.gguf" ;;
    4B)        LM_FILE="acestep-5Hz-lm-4B-Q8_0.gguf" ;;
    *) echo "[models] Unsupported ACESTEP_CPP_LM_SIZE='${LM_SIZE}' (use 0.6B, 1.7B or 4B)" >&2; exit 2 ;;
esac

FILES=(
    "vae-BF16.gguf"
    "Qwen3-Embedding-0.6B-Q8_0.gguf"
    "${LM_FILE}"
    "acestep-v15-${DIT_VARIANT}-${QUANT}.gguf"
)

# SHA-256 values for the default verified Open Studio model set.
declare -A SHA256=(
    ["vae-BF16.gguf"]="0599862ac5d15cd308e1d2e368373aea6c02e25ebd1737ad4a4562a0901b0ef8"
    ["Qwen3-Embedding-0.6B-Q8_0.gguf"]="972f23255e46adfe744a0eb9a0039f3c63988f65753b0968d776e8b27168c321"
    ["acestep-5Hz-lm-0.6B-Q8_0.gguf"]="bdaf9e292d4470f31c19cafeaca1b74936a114667e3a85e5d33b65247e9908ec"
    ["acestep-5Hz-lm-1.7B-Q8_0.gguf"]="726f99a82f050b32ebc5c5e36acaa9d7acd06bfe5e579a62b00e0d0d6d0b7ec6"
    ["acestep-5Hz-lm-4B-Q8_0.gguf"]="972f91147a167f0c041f1b158d67985a82c0f6a852e68cdf70e46030cf08b1bc"
    ["acestep-v15-base-Q8_0.gguf"]="10329f321010cedc3571c24b6371d002ce49238f48be47def4a1c76bf27ee150"
    ["acestep-v15-sft-Q8_0.gguf"]="17f1984e48aaab27b3eb8ccbf0b754a6656e677884c60ea7003845cfc0059b70"
    ["acestep-v15-turbo-Q8_0.gguf"]="288f708a61cfc241013a98a62f98ba331f83fe34d0d3559acdd9b0f6a2f7cd6b"
    ["acestep-v15-turbo-continuous-Q8_0.gguf"]="ed50670ad55ab53bd1c753529e3b6a8e58512e1c5f4df15426948c73fd407abf"
    ["acestep-v15-turbo-shift1-Q8_0.gguf"]="3cc621a46b0d4906c0bce09c7b8d563bdc1aa39a4b4856271045bae12287027c"
    ["acestep-v15-turbo-shift3-Q8_0.gguf"]="21cc9ec83378c71a28aef4a5c1bacab3fe5025e9de8f76487656b6f9de330d21"
    ["acestep-v15-xl-base-Q8_0.gguf"]="45d05b88ccbfa0ea27208ea618d7f0749b2be040b457cfa661d37646ea39f207"
)

check_only=0
if [ "${DOWNLOAD}" != "true" ]; then
    check_only=1
fi

mkdir -p "${MODELS_DIR}"

echo "[models] Directory: ${MODELS_DIR}"
echo "[models] Preset: DiT=acestep-v15-${DIT_VARIANT}-${QUANT}, LM=${LM_SIZE}, text-encoder=Q8_0, VAE=BF16"
echo "[models] A complete first run downloads several gigabytes (about 4.4 GB for the default Q8_0 set)."

missing=0
for file in "${FILES[@]}"; do
    if [ -s "${MODELS_DIR}/${file}" ]; then
        echo "[models] present: ${file}"
    else
        missing=$((missing + 1))
        if [ "${check_only}" = "1" ]; then
            echo "[models] missing: ${file}" >&2
        fi
    fi
done

if [ "${missing}" -eq 0 ]; then
    echo "[models] All required GGUF files are present."
    exit 0
fi

if [ "${check_only}" = "1" ]; then
    echo "[models] ACESTEP_CPP_DOWNLOAD_MODELS=false and ${missing} file(s) are missing." >&2
    echo "[models] Set ACESTEP_CPP_DOWNLOAD_MODELS=true or mount a complete model directory." >&2
    exit 1
fi

free_kb=$(df -Pk "${MODELS_DIR}" | awk 'NR==2 {print $4}')
if [ -n "${free_kb}" ] && [ "${free_kb}" -lt 5000000 ]; then
    echo "[models] WARNING: less than 5 GB free in the model volume. The download may fail." >&2
fi

for file in "${FILES[@]}"; do
    target="${MODELS_DIR}/${file}"
    if [ -s "${target}" ]; then
        continue
    fi
    echo "[models] downloading ${file}…"
    tmp="${target}.part"
    curl --fail --location --retry 5 --retry-delay 4 --connect-timeout 30 \
        --continue-at - \
        --output "${tmp}" \
        "${BASE_URL}/${file}"
    mv "${tmp}" "${target}"
    expected="${SHA256[${file}]:-}"
    if [ -n "${expected}" ] && [ "${ACESTEP_CPP_VERIFY_SHA256:-true}" != "false" ]; then
        if ! command -v sha256sum >/dev/null 2>&1; then
            echo "[models] sha256sum unavailable; skipping integrity check for ${file}" >&2
        else
            actual=$(sha256sum "${target}" | awk '{print $1}')
            if [ "${actual}" != "${expected}" ]; then
                echo "[models] SHA-256 mismatch for ${file}" >&2
                echo "[models] expected ${expected}" >&2
                echo "[models] got      ${actual}" >&2
                rm -f "${target}"
                exit 3
            fi
            echo "[models] checksum ok: ${file}"
        fi
    elif [ -z "${expected}" ]; then
        echo "[models] no pinned checksum for custom selection: ${file}"
    fi
    echo "[models] ready: ${file}"
done

echo "[models] Download complete."
