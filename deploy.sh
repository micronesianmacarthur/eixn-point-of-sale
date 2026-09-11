#!/usr/bin/env bash
# ───────────────────────────────────────────────────
# 13.5 — Container Registry Pipeline
# Pulls latest images, restarts stack, prunes unused.
# ───────────────────────────────────────────────────
set -euo pipefail

echo "=== EIXN POS Deploy ==="

cd "$(dirname "$0")"

echo "[1/3] Pulling latest images..."
docker compose pull

echo "[2/3] Restarting stack..."
docker compose up -d --remove-orphans

echo "[3/3] Pruning unused Docker resources..."
# NOTE: deliberately no --volumes — `docker system prune --volumes` can
# destroy the PostgreSQL data volume (pgdata) if it detaches from compose.
docker system prune -f

echo "=== Deploy complete ==="
