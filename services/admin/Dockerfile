FROM docker:27-cli AS dockercli

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/shared/python \
    SERVICE_NAME=admin \
    HOME=/data/home

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

COPY shared/python /app/shared/python
COPY services/__init__.py /app/services/__init__.py
COPY services/admin/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY services/admin /app/services/admin

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=20s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "services.admin.main:app", "--host", "0.0.0.0", "--port", "8000"]
