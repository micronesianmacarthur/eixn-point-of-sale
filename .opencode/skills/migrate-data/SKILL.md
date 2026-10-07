---
name: migrate-data
description: Create and verify Django data migrations safely in this repo. Use when adding a RunPython data migration, a backfill, or a field/choices change that alters existing rows. Guards the real dev database localhost:5433.
---

# Data migrations are not covered by the test suite

Django builds the test DB by running migrations, so a `RunPython` step executes against an
*empty* table and a broken backfill still goes green.

## Rules

- The dev DB `eixn_pos` (localhost:5433) holds real data — NEVER run
  `manage.py migrate` / `migrate <app> <n>` against it. A round-trip rewrites real schema and
  rows; rolling a data migration backwards is lossy.
- Exercise migrations via `manage.py test <app>` (builds a throwaway `test_eixn_pos`) or a
  scratch DB (`DATABASE_URL=postgres://eixn:eixn@172.20.0.2:5432/eixn_pos`).
- If you must touch the dev DB, `manage.py dumpdata` first.

## Verify a new data migration

1. `manage.py makemigrations --check --dry-run` — a TextChoices label-only change still emits
   a migration; catch drift here.
2. On the scratch DB, exercise the real pre-migration schema:
   - migrate back to the pre-migration state: `manage.py migrate <app> <previous>`
   - insert legacy rows matching the pre-migration schema
   - migrate forward and assert the conversion produced the expected values
   - run the reverse path and assert it restores the original values
3. Trust `information_schema` / `django_migrations`, not `showmigrations`: it only lists
   migration *files* on the current branch, so after a branch switch it under-reports a DB that is
   actually ahead (symptom: `column <table>.<field> does not exist`).

## Existing data migrations

`core/0002`, `core/0004`, `core/0005`, `users/0003` are the known RunPython ones on `main`.