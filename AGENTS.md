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
- The full suite is red at baseline: all 4 tests in `users/tests.py` (`UserManagementDeleteTests`) fail, because that class creates no `BusinessInfo` and every request gets 302-redirected to `/setup/` — i.e. it violates the rule above. Adding `BusinessInfo.objects.get_or_create(business_name='Test Shop')` to its `setUp` makes all 4 pass (verified). Do not treat these as a regression you caused.
- **Data migrations are not covered by the test suite.** Django builds the test database by running migrations, so `RunPython` steps execute against an *empty* table and a broken backfill still goes green. When adding one, verify it against a real pre-migration schema: migrate back, insert legacy rows, migrate forward, assert the conversion — and assert the reverse path restores the original values. `main` has four such migrations (`core/0002`, `core/0004`, `core/0005`, `users/0003`).
- **The dev database holds real data.** `eixn_pos` (localhost:5433) is the user's working database, so never verify a migration with `manage.py migrate` / `migrate <app> <n>` against it — a round-trip rewrites real schema and rows. Exercise migrations via `manage.py test <app>` (which builds a throwaway `test_eixn_pos`) or a scratch database. If you must touch the dev database, take a dump first (`manage.py dumpdata`) and remember that rolling a data migration backwards is lossy.
- `showmigrations` only lists migration *files* it can find on the current branch. After switching branches it can therefore under-report a database that is actually ahead, which looks like a phantom "nothing applied" state. Trust `information_schema` / `django_migrations` over `showmigrations` when the code and schema seem to disagree — the usual symptom is `column <table>.<field> does not exist`.
- `ManagerOrAdminMixin` (per-app copies in `users/views.py`, `customers/views.py`, `inventory/views.py`) uses `UserPassesTestMixin`, which returns **403, not 302** — tests must assert 403 for unauthorized users.
- Auth backend is `users.backends.PinOrPasswordBackend` (PIN or password login).