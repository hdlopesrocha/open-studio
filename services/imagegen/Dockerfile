FROM python:3.12-slim

# Build a CPU image by default. For CUDA use:
#   --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu124
# Set INSTALL_DIFFUSERS=0 for a small image that only serves procedural artwork.
ARG INSTALL_DIFFUSERS=1
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=imagegen \
    IMAGEGEN_MODELS_DIR=/data/models/images \
    VIDEO_PROJECTS_ROOT=/data/files/video/projects \
    COMFYUI_URL=http://comfyui:8188 \
    QVAC_URL=http://qvac:8000 \
    HF_HOME=/data/models/huggingface \
    HF_HUB_CACHE=/data/models/huggingface/hub

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/imagegen/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/imagegen/requirements-diffusers.txt /app/requirements-diffusers.txt
RUN if [ "$INSTALL_DIFFUSERS" = "1" ]; then \
      pip install torch --index-url "$TORCH_INDEX_URL" && \
      pip install -r /app/requirements-diffusers.txt; \
    fi

COPY services/imagegen /app/services/imagegen
RUN mkdir -p /data/files /data/state /data/cache /data/models/images /data/artifacts

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=25s \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.imagegen.main:app", "--host", "0.0.0.0", "--port", "8000"]
