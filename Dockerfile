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
RUN pip install --upgrade pip && pip install -e .

COPY alembic.ini ./
COPY alembic ./alembic
COPY config ./config
COPY src ./src
COPY scripts ./scripts

RUN useradd --create-home --uid 1001 fantasy \
 && mkdir -p /app/logs /mnt/data/fantasy-edge/models \
 && chown -R fantasy:fantasy /app /mnt/data/fantasy-edge
USER fantasy

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
