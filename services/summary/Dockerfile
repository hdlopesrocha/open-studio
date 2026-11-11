FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=summary \
    OMP_NUM_THREADS=4 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/data/models/.hf-cache \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/models/summary /data/models/.hf-cache /data/files /data/state

COPY shared/python /app/shared/python
COPY services/summary/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/summary/app /app/app
COPY services/summary/README.md /app/README.md
RUN printf '#!/bin/sh\nexec python -m app.download_models "$@"\n' > /usr/local/bin/download-models \
    && chmod 0755 /usr/local/bin/download-models

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
