FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=video-animation \
    PROJECTS_ROOT=/data/files/video/projects \
    CACHE_ROOT=/data/cache/video \
    MODELS_ROOT=/data/models \
    CONFIG_ROOT=/data/state/video

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        fonts-dejavu-core \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/video-animation/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY services/video-animation /app/services/video_animation

RUN mkdir -p /data/files/video/projects /data/cache/video /data/state/video /data/models

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=25s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.video_animation.app:app", "--host", "0.0.0.0", "--port", "8000"]
