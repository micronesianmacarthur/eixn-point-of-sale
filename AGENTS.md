# Project Instructions

## Git Workflow (Mandatory)

- NEVER run `git commit`, `git merge`, or `git push` without the user's explicit instruction to do so.
- Before any commit/merge/push, present the changes for the user to review and wait for their approval.
- Only stage files the user intends to include; never commit secrets or unrelated files.
- Feature work happens on `<app>/<name>` branches (the Django app is the prefix, e.g. `sales/split-payment`, `inventory/count-sheet`), merged to `main` with `--no-ff`, then the branch is deleted.

## Conventions

- Log every change in `docs/progress.md`, organized under the correct `## YYYY-MM-DD` heading (newest entry at the top of the file, in the dated section matching the day the change was made).
- Django backend lives in `backend/`; use `backend/.venv/bin/python manage.py ...` (settings module `core.settings`).
- No linter, formatter, or type checker is configured. Verify changes with `manage.py check` and `manage.py test <app>` (tests live in each app's `tests.py`).
- Business logic goes in per-app `services.py` (e.g. `process_checkout`, `post_stock_count`); analytics helpers in `sales/analytics.py`; receipt formatting in `sales/receipts.py`; async background work in `core/tasks.py` via django-q2 (`async_task('core.tasks.print_receipt', txn.id)`) — never block the request.
- Money is always `Decimal`, never float; quantize to 0.01 with `ROUND_HALF_UP` (see `inventory/services.py:post_stock_count`).
- Frontend stack: Django templates + Tailwind CSS (CLI-built, not CDN), Alpine.js, HTMX. Tailwind v4 is a root-level devDependency; input is `frontend/app.css`, compiled to `backend/static/css/app.css` by `npm run build` (runs `scripts/vendor-static.mjs`, `tailwindcss --minify`, then `scripts/verify-static.mjs`). Classes added to a template are silently absent from the compiled CSS until a rebuild — after template changes run `npm run build` and confirm the class count unchanged/expected (verify prints the total).
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
- `manage.py test` with no test label runs **0 tests** and reports success — always pass explicit labels (e.g. `manage.py test sales.tests.ReceiptTests users core customers inventory`).
- The dev DB (localhost:5433) is often unavailable; run tests against the scratch container with `DATABASE_URL=postgres://eixn:eixn@172.20.0.2:5432/eixn_pos`. Drop a stale test DB first: `docker exec eixn-point-of-sale-db-1 psql -U eixn -d postgres -c "DROP DATABASE IF EXISTS test_eixn_pos WITH (FORCE);"`.
- Django's test `Client()` sends `HTTP_HOST=testserver`, which trips `DisallowedHost` (ALLOWED_HOSTS is env-driven, empty by default) — pass `HTTP_HOST='localhost'`.
- **WeasyPrint drops nothing of ours but Tailwind v4 emits `@layer` rules, which WeasyPrint ignores** — print output via WeasyPrint looks unstyled. Verify printed pages with headless Chromium instead: serve `backend/` with `python3 -m http.server <port>`, then `/usr/bin/chromium --headless=new --no-sandbox --no-pdf-header-footer --print-to-pdf=out.pdf <url>`, then inspect with `pdftotext -bbox`.
- Receipt/print verification recipe: render the template through the test client inside `transaction.atomic()` + `set_rollback(True)` (seed a demo sale, `force_login`, write `response.content` to a file), serve `backend/`, Chromium-print, `pdftotext -bbox` to check coordinates (e.g. label right edges should land on the same x).
- Shell traps: `pkill -f <pattern>` matches the calling shell's own command line and kills the session — stop throwaway servers with `pgrep -ax python3 | awk '/http.server <port>/ {print $1}'` + kill by PID instead. Port 8091 is occupied by another service (Prowlarr); demo print servers have used 8867.
- The POS display term for `STORE_CREDIT` is **"Account"** (model label in `sales/models.py`, checkout buttons, and receipt legs all print it). Hardcoded `"Store Credit"` strings left in `session_close.html`, `offline_recovery.html`, `zreport_content.html` are stale leftovers, not a convention to copy.
- A `TextChoices` label-only change still produces a migration (e.g. `sales/0010_alter_payment_payment_type.py`) — run `makemigrations --check --dry-run` to catch drift.