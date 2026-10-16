# syntax=docker/dockerfile:1
# One container: FastAPI (public PORT) + Baileys gateway (127.0.0.1:3001), run by supervisord.

FROM node:22-bookworm-slim AS web
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS gateway
WORKDIR /build/wa-gateway
COPY wa-gateway/package.json wa-gateway/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY wa-gateway/tsconfig.json ./
COPY wa-gateway/src ./src

# HyperFrames (Apache-2.0) renders the opt-in brag-style motion layer.
FROM node:22-bookworm-slim AS render
WORKDIR /build/render
RUN npm init -y >/dev/null && npm install --no-audit --no-fund hyperframes@0.8.166

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENV=prod \
    PORT=8000 \
    MEDIA_DIR=/data/media \
    ASSETS_DIR=/app/assets \
    STATIC_DIR=/app/backend/app/static \
    WHISPER_MODEL_DIR=/models/whisper \
    HYPERFRAMES_CLI=/app/render/node_modules/hyperframes/bin/hyperframes.mjs

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg supervisor ca-certificates fonts-dejavu-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

# Chromium's shared libraries for the HyperFrames headless browser. If any of this fails, motion graphics are
# simply unavailable at runtime (the standard FFmpeg edit always works).
ARG WITH_HYPERFRAMES=1
RUN if [ "$WITH_HYPERFRAMES" = "1" ]; then \
      (apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*) \
      || echo "chromium install failed: motion graphics disabled"; \
    fi
COPY --from=render /build/render /app/render
RUN if [ "$WITH_HYPERFRAMES" = "1" ]; then \
      node /app/render/node_modules/hyperframes/bin/hyperframes.mjs browser ensure \
      || echo "hyperframes browser download failed: motion graphics disabled"; \
    else rm -rf /app/render; fi

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

ARG WHISPER_MODEL=small
ENV WHISPER_MODEL=${WHISPER_MODEL}
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/models/whisper')"

COPY assets assets
COPY backend/app backend/app
COPY --from=gateway /build/wa-gateway wa-gateway
COPY --from=web /build/frontend/dist backend/app/static
COPY supervisord.conf /etc/supervisor/conf.d/app.conf
RUN mkdir -p /data/media

EXPOSE 8000
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/app.conf"]
