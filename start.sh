#!/bin/sh
# Entrypoint : migrations Alembic puis lancement de l'API.
# Render injecte $PORT (généralement 10000) ; fallback 8000 en local.
set -e

echo "[start.sh] Environnement : ${ENVIRONMENT:-production}"
echo "[start.sh] Base de données : ${DATABASE_URL%%@*}@***"

echo "[start.sh] Application des migrations Alembic..."
alembic upgrade head
echo "[start.sh] Migrations OK."

WORKERS="${WORKERS:-1}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo "[start.sh] Démarrage uvicorn — host=0.0.0.0 port=$PORT workers=$WORKERS"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL" \
    --no-access-log
