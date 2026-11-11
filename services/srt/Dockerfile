FROM python:3.12-slim

ARG INSTALL_CUDA=0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=srt \
    WHISPER_CACHE_DIR=/data/models/whisper \
    WHISPER_DEVICE=auto \
    HF_HOME=/data/models/huggingface

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/srt/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Optional CUDA runtime libraries for CTranslate2. Build with:
#   docker build --build-arg INSTALL_CUDA=1 ...
# and run with the NVIDIA container runtime. CTranslate2 4.x targets CUDA 12.
RUN if [ "$INSTALL_CUDA" = "1" ]; then \
      pip install "nvidia-cublas-cu12>=12.4" "nvidia-cudnn-cu12>=9.1"; \
    fi
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

COPY services/srt /app/services/srt
RUN mkdir -p /data/files /data/state /data/cache /data/models/whisper /data/artifacts

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=25s \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.srt.main:app", "--host", "0.0.0.0", "--port", "8000"]
