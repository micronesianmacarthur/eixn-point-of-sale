#!/bin/bash
set -e

# ─────────────────────────────────────────────
# Local dev environment bootstrap
# Starts a Docker PostgreSQL container (if not
# already running), runs migrations, and seeds
# the admin user (admin / admin).
#
# Prerequisites: Docker
# ─────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../backend"

PYTHON="$SCRIPT_DIR/../backend/.venv/bin/python3"
DB_PORT=5433
CONTAINER_NAME=eixn-pos-db

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "==> Starting PostgreSQL container on port ${DB_PORT}..."
  docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
  docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_DB=eixn_pos \
    -e POSTGRES_USER=eixn \
    -e POSTGRES_PASSWORD=eixn \
    -p ${DB_PORT}:5432 \
    -v eixn-pos-pgdata:/var/lib/postgresql/data \
    postgres:16-alpine
  # Wait for PostgreSQL to be ready
  for i in $(seq 1 30); do
    if PGPASSWORD=eixn psql -h localhost -p ${DB_PORT} -U eixn -d eixn_pos -c "SELECT 1;" >/dev/null 2>&1; then
      break
    fi
    echo "    Waiting for PostgreSQL... (${i}s)"
    sleep 1
  done
else
  echo "==> PostgreSQL container already running."
fi

echo "==> Running migrations..."
$PYTHON manage.py migrate --noinput

echo "==> Seeding admin user (admin / admin)..."
$PYTHON manage.py shell -c "
from users.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='admin', role=User.Role.ADMIN)
    print('    Admin user created.')
else:
    print('    Admin user already exists.')
"

echo ""
echo "Done! Run the dev server with:"
echo "  cd backend && python3 manage.py runserver"
echo ""
echo "To stop the database:"
echo "  docker stop ${CONTAINER_NAME} && docker rm ${CONTAINER_NAME}"
