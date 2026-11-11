FROM node:22-bookworm

ENV NODE_ENV=production \
    PORT=8000 \
    DATA_ROOT=/data \
    FILES_ROOT=/data/files \
    MODELS_ROOT=/data/models \
    STATE_ROOT=/data/state \
    CACHE_ROOT=/data/cache \
    SERVICE_NAME=qvac

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libvulkan1 \
        mesa-vulkan-drivers \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY services/qvac/package.json services/qvac/package-lock.json* /app/
RUN if [ -f /app/package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi

COPY services/qvac /app

RUN mkdir -p /data/files /data/state /data/cache /data/models /data/artifacts \
    && chmod +x /app/index.js

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --retries=8 --start-period=30s \
    CMD node -e "fetch('http://127.0.0.1:8000/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "index.js"]
