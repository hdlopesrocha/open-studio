# syntax=docker/dockerfile:1
#
# Open Studio music engine: ACE-Step 1.5 through the GGML/C++ implementation.
# CPU by default; optionally build with Vulkan for AMD/Intel GPUs.
#
# Build from the repository root (compose context):
#   docker build -f engines/acestep-cpp/Dockerfile -t openstudio-music-engine .
#
# Build with Vulkan:
#   docker build -f engines/acestep-cpp/Dockerfile --build-arg ENABLE_VULKAN=1 -t openstudio-music-engine:vulkan .

ARG DEBIAN_VERSION=bookworm
FROM debian:${DEBIAN_VERSION}-slim AS build

ARG ACESTEP_CPP_REPOSITORY=https://github.com/ServeurpersoCom/acestep.cpp.git
ARG ACESTEP_CPP_REF=07abf07da3a9c1c45bd85aabed401644f8eb7c72
ARG ENABLE_VULKAN=0

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libopenblas-dev \
        pkg-config \
        libvulkan-dev \
        glslc \
    && rm -rf /var/lib/apt/lists/*

RUN git init /src \
    && cd /src \
    && git remote add origin "${ACESTEP_CPP_REPOSITORY}" \
    && git fetch --depth 1 origin "${ACESTEP_CPP_REF}" \
    && git checkout --detach FETCH_HEAD \
    && git submodule update --init --recursive --depth 1

WORKDIR /src
RUN EXTRA_FLAGS=""; \
    if [ "${ENABLE_VULKAN}" = "1" ]; then EXTRA_FLAGS="-DGGML_VULKAN=ON"; fi; \
    cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_BLAS=ON \
        ${EXTRA_FLAGS} \
    && cmake --build build --config Release -j"$(nproc)"

FROM debian:${DEBIAN_VERSION}-slim AS runtime

ARG ENABLE_VULKAN=0

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgomp1 \
        libopenblas0 \
        libstdc++6 \
        libvulkan1 \
        mesa-vulkan-drivers \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 openstudio \
    && useradd --uid 10001 --gid openstudio --create-home --shell /usr/sbin/nologin openstudio \
    && mkdir -p /opt/acestep /data/models/acestep /data/state /data/cache \
    && chown -R openstudio:openstudio /opt/acestep /data/models /data/state /data/cache

COPY --from=build /src/build/ace-server /opt/acestep/ace-server
COPY --from=build /src/build/libggml*.so* /opt/acestep/
COPY --from=build /src/LICENSE /opt/acestep/LICENSE
COPY --chown=openstudio:openstudio engines/acestep-cpp/download-models.sh /opt/acestep/download-models.sh
COPY --chown=openstudio:openstudio engines/acestep-cpp/entrypoint.sh /opt/acestep/entrypoint.sh

RUN chmod +x /opt/acestep/ace-server /opt/acestep/download-models.sh /opt/acestep/entrypoint.sh

ENV LD_LIBRARY_PATH=/opt/acestep \
    ACESTEP_CPP_MODELS_DIR=/data/models/acestep \
    ACESTEP_CPP_DEVICE=CPU \
    ACESTEP_CPP_DOWNLOAD_MODELS=true \
    ACESTEP_CPP_QUANT=Q8_0 \
    ACESTEP_CPP_LM_SIZE=0.6B \
    ACESTEP_CPP_KEEP_LOADED=false \
    ACESTEP_CPP_PORT=8085

USER openstudio
WORKDIR /opt/acestep
EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=10s --start-period=1800s --retries=5 \
    CMD curl -sf http://127.0.0.1:8085/health >/dev/null 2>&1 || exit 1

ENTRYPOINT ["/opt/acestep/entrypoint.sh"]
