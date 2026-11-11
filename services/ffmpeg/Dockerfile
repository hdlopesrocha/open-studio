FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=ffmpeg \
    FILES_ROOT=/data/files \
    DATA_ROOT=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
        fonts-noto-core \
        fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/ffmpeg/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt \
    && ffmpeg -version >/dev/null \
    && ffprobe -version >/dev/null

COPY services/ffmpeg /app/services/ffmpeg

RUN mkdir -p /data/files /data/state /data/cache /data/models /data/artifacts \
    && fc-cache -f >/dev/null 2>&1 || true

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.ffmpeg.main:app", "--host", "0.0.0.0", "--port", "8000"]
