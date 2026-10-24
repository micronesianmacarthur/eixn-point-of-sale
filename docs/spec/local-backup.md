# Spec: Local Backup & Restore (eixnPOS)

## Objective
Add a local database backup and full-restore feature to the eixnPOS settings "Backup & Restore" tab for admin and manager users.

- **Backup:** server-side `pg_dump` of the PostgreSQL database → compressed `.sql.gz` → browser download to Downloads folder. Tip text tells the user to move the file to their preferred folder.
- **Restore:** `<input type="file">` upload → server-side `pg_restore` → full database restore (wipes current data and replaces with snapshot).
- Both actions must not break the existing settings UI, cloud backup, or dashboard backup widget.

## Tech Stack
- Django 5.2.15, Python 3.14 (`.python-version`)
- PostgreSQL 16 (via `pg_dump` / `pg_restore` system binaries)
- Dependency management: `uv` (`backend/uv.lock`)
- Frontend: Django templates + HTMX + Alpine.js + Tailwind v4 (already in repo)
- Background queue: django-q2 (already configured, not used for local backup — actions are synchronous user-triggered)

## Commands
```bash
# Install / sync dependencies (from repo root)
cd backend && uv sync

# Django checks
backend/.venv/bin/python manage.py check
backend/.venv/bin/python manage.py makemigrations --check --dry-run

# Run tests (explicit labels — `manage.py test` with no label runs 0 tests)
backend/.venv/bin/python manage.py test sales core customers inventory accounting users

# New commands (to be implemented)
backend/.venv/bin/python manage.py local_backup
backend/.venv/bin/python manage.py local_restore <path-to-backup-file>

# Frontend build (after any template class changes)
npm run build
```

## Project Structure
```
eixn-point-of-sale/
├── docs/intent/local-backup.md          # confirmed intent (this session)
├── docs/spec/local-backup.md            # this spec
├── backend/
│   ├── core/
│   │   ├── management/
│   │   │   └── commands/
│   │   │       ├── cloud_backup.py      # existing — do not modify
│   │   │       ├── ensure_backup_schedule.py  # existing — do not modify
│   │   │       ├── local_backup.py      # NEW: pg_dump → download .sql.gz
│   │   │       └── local_restore.py     # NEW: upload → pg_restore full restore
│   │   ├── settings.py                  # existing — no changes expected
│   │   └── tasks.py                     # existing — cloud backup wrapper
│   ├── sales/
│   │   ├── views.py                     # existing — add local backup/restore views
│   │   ├── urls.py                      # existing — add local backup/restore routes
│   │   └── templates/
│   │       └── core/
│   │           └── settings.html        # existing — wire Backup & Restore tab
│   └── backups/                         # local dump storage
```

## Code Style
Per `AGENTS.md` conventions:
- Variables: `snake_case`; Classes: `PascalCase`; Constants: `UPPERCASE`
- Money is `Decimal` (not directly applicable to backup, but follow the spirit: no floats for anything numeric)
- Business logic in per-app `services.py` where complex; management commands for CLI operations
- No linter/formatter configured — verify with `manage.py check` and `manage.py test <app>`
- Never commit `backend/.env`; only `.env.example` is tracked
- Management command help text and stdout messages use `self.stdout.write()` / `self.style.SUCCESS()`

Example snippet (management command pattern):
```python
class Command(BaseCommand):
    help = "Dump the PostgreSQL database to a compressed .sql.gz file."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, help="Destination path for the backup file.")

    def handle(self, *args, **options):
        ...
        self.stdout.write(self.style.SUCCESS(f"Backup written to {dump_path}"))
```

## Testing Strategy
- Framework: Django test framework (`manage.py test <app>`)
- Test locations: each app's `tests.py`
- Always pass explicit test labels: `manage.py test sales core customers inventory accounting users`
- `manage.py test` with no label runs 0 tests and reports success — never rely on it
- Tests must create `BusinessInfo` where authenticated requests are made (SetupCheckMiddleware 302-redirects without it)
- Verify backup command produces a valid gzip file; verify restore command reads a backup and restores data (use throwaway test DB via `manage.py test`, never the dev DB at localhost:5433)
- UI: verify settings tab renders without errors for admin and manager users (HTMX/Alpine intact, no raw data dumps)

## Boundaries
- **Always:** Run `manage.py check` and `manage.py test <app>` before considering a change done; follow naming conventions; validate all inputs (uploaded file must be a valid gzip/sql dump); never block the request thread long-term without user awareness.
- **Ask first:** Any change to `settings.py`, adding new dependencies (`uv add`), changing CI config, modifying `cloud_backup.py` or the dashboard backup widget.
- **Never:** Commit secrets or `.env`; edit vendor directories; remove failing tests without approval; run `manage.py migrate` against the dev database (`eixn_pos` on localhost:5433) — use `manage.py test` (throwaway `test_eixn_pos`) or a scratch database instead.

## Success Criteria
1. `manage.py local_backup` produces a valid `.sql.gz` in `backend/backups/` and writes `last_backup.txt` marker.
2. `manage.py local_restore <file>` restores the full database from that file into the throwaway test DB and asserts data integrity.
3. Settings "Backup & Restore" tab renders for admin and manager with "Backup Now" (download) and "Restore from file" (upload) controls; no raw dictionaries, no stray numbers, no broken layout.
4. `manage.py check` clean; `makemigrations --check --dry-run` clean; existing test suite green (112+ tests as of last progress log).
5. Cloud backup dashboard widget and `BackupTriggerView` unchanged and still functional.

## Open Questions
- Should "Backup Now" trigger synchronously in the request (user waits for download) or via django-q2 background task (download link appears when ready)? Sync is simpler and matches the existing `BackupTriggerView` pattern.
- Should the settings tab list existing local backups with per-file restore, or just a single "Restore from file" upload? Simpler: upload-only restore first; listing can be added later.
- Should restore require re-login / session refresh after a full DB restore? **Yes — force re-login** (user confirmed). A full DB wipe invalidates existing sessions; the restore view should log the user out and redirect to login.