FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgomp is required by both xgboost and lightgbm at import time; without it
# they fail with an opaque "libgomp.so.1: cannot open shared object file".
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY requirements-runtime.lock ./
# Install every runtime transitive dependency at its reviewed version. The
# constraint also makes changed project requirements fail instead of drifting.
RUN pip install -r requirements-runtime.lock \
 && pip install -e . -c requirements-runtime.lock \
 && pip check

COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config
COPY src ./src
COPY scripts ./scripts

# Seal only after the final source COPY, so API and worker images have the
# same content identity. The manifest never includes .env or raw archives.
RUN python scripts/backend_release_manifest.py seal --root /app

RUN useradd --create-home --uid 1001 fantasy \
 && mkdir -p /app/logs /mnt/data/fantasy-edge/models /mnt/data/fantasy-edge/raw \
 && chown -R fantasy:fantasy /app /mnt/data/fantasy-edge
USER fantasy

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
