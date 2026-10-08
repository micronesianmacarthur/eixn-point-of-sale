#!/usr/bin/env bash
set -e

# Resolve repository root
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
BACKEND_DIR="$REPO_ROOT/backend"

# Start Tailwind watch in background
echo "Starting Tailwind CSS watcher..."
cd "$FRONTEND_DIR"
npm run css:watch &
TAILWIND_PID=$!
echo "Tailwind watcher PID: $TAILWIND_PID"

# Change to backend and run dev server
cd "$BACKEND_DIR"
echo "Starting Django development server..."
.venv/bin/python3 manage.py runserver

# When Django server stops, clean up
echo "Stopping Tailwind watcher..."
kill $TAILWIND_PID 2>/dev/null || true