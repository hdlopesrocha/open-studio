# syntax=docker/dockerfile:1

# Build the CPU image (default):
#   docker build -f services/voice/Dockerfile \
#     --build-arg DEVICE=cpu \
#     --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu \
#     -t openstudio-voice .
#
# Build the CUDA image (pick the index matching the host driver):
#   docker build -f services/voice/Dockerfile \
#     --build-arg DEVICE=cuda \
#     --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128 \
#     -t openstudio-voice:cu128 .
#
# Compose must pass the same DEVICE value to the runtime container. OmniVoice
# is imported lazily: if the package is unavailable the service still starts,
# reports status=unavailable, and Piper remains usable.

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.8.0

FROM python:3.11-slim

ARG TORCH_INDEX_URL
ARG TORCH_VERSION
ARG DEVICE=cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=voice \
    DEVICE=${DEVICE} \
    HF_HOME=/data/models/huggingface \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=4

# ffmpeg/libsndfile handle WAV/MP3/FLAC conversion and duration probes.
# build-essential + cmake/ninja cover source builds pulled by the OmniVoice
# text-normalization extras; curl is used by the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        ffmpeg \
        git \
        libgomp1 \
        libsndfile1 \
        ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Install the accelerator-specific PyTorch build first. The rest of the
# requirements then see torch as already satisfied.
RUN python -m pip install --upgrade pip \
    && python -m pip install --index-url "${TORCH_INDEX_URL}" \
        "torch==${TORCH_VERSION}" \
        "torchaudio==${TORCH_VERSION}"

WORKDIR /app

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/voice/requirements.txt /app/requirements.txt
RUN python -m pip install -r /app/requirements.txt

COPY services/voice /app/services/voice

RUN mkdir -p /data/files /data/state /data/cache /data/models /data/artifacts \
        /data/models/piper /data/models/huggingface /data/files/voices/piper \
    && printf '#!/bin/sh\nexec python -m services.voice.download_models "$@"\n' \
        > /usr/local/bin/voice-download-models \
    && chmod +x /usr/local/bin/voice-download-models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=45s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# One worker only: the OmniVoice model and Piper voice cache live in-process.
CMD ["uvicorn", "services.voice.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--timeout-keep-alive", "600"]
