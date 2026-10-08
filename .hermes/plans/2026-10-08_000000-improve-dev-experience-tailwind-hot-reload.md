# Plan: Improve Local Development Experience with Tailwind CSS Hot Reload

## Goal
Enable hot-reload for Tailwind CSS changes in the EIXN POS project to improve local development experience by automatically recompiling CSS when frontend/app.css is modified, eliminating the need to manually run the Tailwind build command.

## Current context / assumptions
- The POS project uses Django for backend and a frontend built with Tailwind CSS, Alpine.js, and HTMX.
- Frontend source CSS is at `frontend/app.css`, compiled to `backend/static/css/app.css`.
- Currently, developers must run `npm run css:watch` in one terminal and `python manage.py runserver` in another to see CSS changes.
- The project uses a Makefile with a `dev` target that currently only runs the Django dev server.
- The project already has a `scripts` directory and uses uv for Python dependencies.

## Architecture / proposed approach
- Create a shell script `scripts/dev.sh` that starts both the Tailwind CSS watcher (in the background) and the Django development server.
- Update the Makefile `dev` target to invoke this script.
- Ensure the script properly cleans up background processes when the Django server stops.
- This approach provides a single command (`make dev`) that starts both services with proper lifecycle management.

## Step-by-step tasks

### Task 1: Create the shell script
Create `scripts/dev.sh` with the following content:
```bash
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
```

### Task 2: Make the script executable
Run:
```bash
chmod +x scripts/dev.sh
```
Expected output: (no output on success)

### Task 3: Update the Makefile
Replace the existing `dev` target in `Makefile` with:
```makefile
dev:    ## Run Django dev server with Tailwind CSS watch (hot reload)
	./scripts/dev.sh
```
After change, the relevant lines should look like:
```makefile
dev:    ## Run Django dev server with Tailwind CSS watch (hot reload)
	./scripts/dev.sh
```

### Task 4: Verify the script works
Run:
```bash
make help | grep dev
```
Expected output:
```
dev        Run Django dev server with Tailwind CSS watch (hot reload)
```

Run a syntax check on the script:
```bash
bash -n scripts/dev.sh
```
Expected output: (no output on success)

Optionally, run the script for a few seconds to see both services start (then interrupt with Ctrl+C):
```bash
timeout 3s ./scripts.dev.sh 2>&1 | head -20
```
Expected output should include:
```
Starting Tailwind CSS watcher...
Tailwind watcher PID: <number>
Starting Django development server...
...
≈ tailwindcss v4.3.3
Done in Xms
```

## Tests / validation
- **Syntax check**: `bash -n scripts/dev.sh` should return exit code 0.
- **Help text verification**: `make help | grep dev` should show the updated description.
- **Process verification**: When running `make dev` in the background, both the Tailwind watcher and Django server processes should be visible (e.g., via `ps aux | grep -E "tailwind|manage.py"`).
- **CSS compilation verification**: After starting `make dev`, modify `frontend/app.css` and save; the file `backend/static/css/app.css` should update within a few seconds (check modification time).

## Risks, tradeoffs, and open questions
- If the Tailwind watcher fails to start (e.g., missing npm dependencies), the script will exit due to `set -e`, but the error message from npm will be visible.
- The script assumes the repository structure (frontend/ and backend/ directories). If the project structure changes, the paths may need updating.
- This setup does not provide hot-reload for Django template or Python changes; developers must still manually reload the browser for those. Consider integrating django-livereload in the future if desired.
- The script uses the local Django server (not Docker) for consistency with the existing `make dev` target. If Docker-based development is preferred, a separate approach would be needed.