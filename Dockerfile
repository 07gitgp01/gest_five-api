# ── Stage 1 : compilation des wheels ─────────────────────────────────────────
# On installe build-essential + libpq-dev seulement dans ce stage ;
# l'image finale n'aura que libpq5 (runtime, ~2 MB vs ~250 MB).
FROM python:3.13-slim AS builder

WORKDIR /build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-deps --wheel-dir /wheels -r requirements.txt


# ── Stage 2 : image de production ────────────────────────────────────────────
FROM python:3.13-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl pour le HEALTHCHECK Docker ; libpq5 pour asyncpg (runtime uniquement)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Wheels compilés dans le stage builder
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# Code applicatif (.dockerignore exclut tests/, .env, __pycache__, *.db, etc.)
COPY . .

# Script de démarrage exécutable
RUN chmod +x start.sh

# Utilisateur non-root (bonne pratique sécurité)
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck Docker interne (distinct du healthCheckPath Render)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# start.sh : alembic upgrade head + uvicorn
CMD ["./start.sh"]
