# Project Instructions

## Git Workflow (Mandatory)

- NEVER run `git commit`, `git merge`, or `git push` without the user's explicit instruction to do so.
- Before any commit/merge/push, present the changes for the user to review and wait for their approval.
- Only stage files the user intends to include; never commit secrets or unrelated files.
- Feature work happens on `feature/<name>` branches, merged to `main` with `--no-ff`, then the branch is deleted.

## Conventions

- Log every change in `docs/progress.md`, organized under the correct `## YYYY-MM-DD` heading (newest entry at the top of the file, in the dated section matching the day the change was made).
- Django backend lives in `backend/`; use `backend/.venv/bin/python manage.py ...` (settings module `core.settings`).
- No linter, formatter, or type checker is configured. Verify changes with `manage.py check` and `manage.py test <app>` (tests live in each app's `tests.py`).
- Business logic goes in per-app `services.py` (e.g. `process_checkout`, `post_stock_count`); analytics helpers in `sales/analytics.py`; receipt formatting in `sales/receipts.py`; async background work in `core/tasks.py` via django-q2 (`async_task('core.tasks.print_receipt', txn.id)`) — never block the request.
- Money is always `Decimal`, never float; quantize to 0.01 with `ROUND_HALF_UP` (see `inventory/services.py:post_stock_count`).
- Frontend stack: Django templates + Tailwind CSS (CDN), Alpine.js, HTMX.
- Never commit `backend/.env`; only `.env.example` is tracked. Configuration comes from env keys (e.g. `PRINTER_HOST`, `S3_*`).

## Naming Conventions

- Variables use `snake_case`.
- Classes use `PascalCase`.
- Constants use `UPPERCASE`.

## Testing Gotchas

- `SetupCheckMiddleware` (`core/middleware.py`) 302-redirects any authenticated user without a `BusinessInfo` row to `/setup/` — tests must create `BusinessInfo`, or they receive 302 instead of 200.
- `ManagerOrAdminMixin` (per-app copies in `users/views.py`, `customers/views.py`, `inventory/views.py`) uses `UserPassesTestMixin`, which returns **403, not 302** — tests must assert 403 for unauthorized users.
- Auth backend is `users.backends.PinOrPasswordBackend` (PIN or password login).