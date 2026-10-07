---
name: run-tests
description: Run this repo's Django suite correctly against the scratch DB container. Use whenever running or interpreting manage.py test output, or when tests are skipped/unexpected. Bare "manage.py test" with no label silently runs 0 tests.
---

# Running tests

## Baseline

`manage.py test` with **no test label runs 0 tests and reports success** — always pass explicit
labels, e.g.: `manage.py test sales.tests.ReceiptTests users core customers inventory`.

The full suite is red at baseline: all 4 tests in `users/tests.py` (`UserManagementDeleteTests`)
fail because that class creates no `BusinessInfo` and every request gets 302-redirected to
`/setup/` (SetupCheckMiddleware). Not a regression — do not "fix" it as part of other work.

## Sequence

1. Drop a stale test DB:
   `docker exec eixn-point-of-sale-db-1 psql -U eixn -d postgres -c "DROP DATABASE IF EXISTS test_eixn_pos WITH (FORCE);"`
2. Run against the scratch container (the dev DB at localhost:5433 is often down):
   `DATABASE_URL=postgres://eixn:eixn@172.20.0.2:5432/eixn_pos backend/.venv/bin/python backend/manage.py test <labels>`
3. After code changes run `manage.py check`; after template changes run `npm run build`
   (Tailwind is CLI-built; `scripts/verify-static.mjs` prints the class-token total).

## Gotchas to honor in tests you write

- `SetupCheckMiddleware` 302-redirects authenticated users without a `BusinessInfo` row — create
  one (`BusinessInfo.objects.get_or_create(business_name='Test Shop')`).
- `ManagerOrAdminMixin` (users/customers/inventory views) returns **403**, not 302.
- Test `Client()` sends `HTTP_HOST=testserver` → `DisallowedHost` (ALLOWED_HOSTS is env-driven,
  empty by default) — pass `HTTP_HOST='localhost'`.
- Auth is `users.backends.PinOrPasswordBackend` (PIN or password login).