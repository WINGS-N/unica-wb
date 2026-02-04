# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS runtime-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    GIT_AUTHOR_NAME="UN1CA Builder" \
    GIT_AUTHOR_EMAIL=builder@local \
    GIT_COMMITTER_NAME="UN1CA Builder" \
    GIT_COMMITTER_EMAIL=builder@local

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    tini \
    && rm -rf /var/lib/apt/lists/*

RUN git config --global user.name "UN1CA Builder" && \
    git config --global user.email "builder@local"

WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

FROM runtime-base AS app-layer
COPY backend/app /app/app
COPY backend/scripts /app/scripts
RUN mkdir -p /data/logs /workspace

FROM app-layer AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8000/api/v1/healthz || exit 1
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/scripts/start-api.sh"]

FROM runtime-base AS worker-base
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    attr \
    bc \
    brotli \
    ccache \
    clang \
    cmake \
    cpio \
    ffmpeg \
    file \
    golang-go \
    libfmt-dev \
    libbrotli-dev \
    libgtest-dev \
    lz4 \
    liblz4-dev \
    libpcre2-dev \
    libprotobuf-dev \
    libunwind-dev \
    libusb-1.0-0-dev \
    libzstd-dev \
    lld \
    make \
    npm \
    default-jdk-headless \
    p7zip-full \
    patchelf \
    pkg-config \
    protobuf-compiler \
    rsync \
    sudo \
    unzip \
    vim-common \
    xxd \
    webp \
    zip \
    zstd \
    && rm -rf /var/lib/apt/lists/*

FROM worker-base AS worker
COPY --from=app-layer /app /app
WORKDIR /app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/scripts/start-worker.sh"]
