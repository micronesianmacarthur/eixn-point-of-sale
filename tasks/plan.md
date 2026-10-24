# Implementation Plan: Local Backup & Restore (eixnPOS)

## Overview
Add a local database backup and full-restore feature to the eixnPOS settings "Backup & Restore" tab for admin and manager users. Backup runs `pg_dump` server-side and downloads a `.sql.gz` to the browser Downloads folder. Restore accepts a file upload, runs `pg_restore` for a full database wipe-and-replace, then forces re-login. No schema changes, no new dependencies, no changes to the existing cloud backup or dashboard widget.

## Architecture Decisions
- **Management commands first:** `local_backup` and `local_restore` live in `core/management/commands/`, mirroring the existing `cloud_backup.py` pattern. Views call them via `call_command()`.
- **Synchronous execution:** Backup/download happens in the request-response cycle (user waits for the download), matching the existing `BackupTriggerView` pattern. No django-q2 for local backup.
- **No schema changes:** `pg_dump`/`pg_restore` operate on the live database directly; no Django models or migrations are added.
- **Force re-login after restore:** A full DB wipe invalidates sessions; the restore view logs the user out and redirects to login.
- **Upload-only restore:** No listing of existing backups in the UI (deferred). The user uploads a `.sql.gz` via `<input type="file">`.
- **RBAC via `ManagerOrAdminMixin`:** Per-app mixin pattern already used in `users`, `customers`, `inventory`. Admin and manager both allowed.
- **No `showSaveFilePicker`:** Browser downloads to Downloads folder; tip text tells the user to move the file manually. Works across all browsers.

## Task List

### Phase 1: Foundation — Management Commands
- [ ] Task 1: `local_backup` management command (`pg_dump` → gzip → `backend/backups/` + `last_backup.txt`)
- [ ] Task 2: `local_restore` management command (`pg_restore` from uploaded `.sql.gz` → full DB restore)

### Checkpoint: Foundation
- [ ] `manage.py check` clean
- [ ] `local_backup` produces a valid `.sql.gz` on a scratch DB
- [ ] `local_restore` restores data into a scratch DB and integrity holds

### Phase 2: Views + URLs
- [ ] Task 3: Backup download view (`POST` → `call_command('local_backup')` → `FileResponse` download)
- [ ] Task 4: Restore upload view (`POST` with file → `call_command('local_restore')` → logout → redirect to login)
- [ ] Task 5: URL routes in `sales/urls.py` for both views

### Checkpoint: Views
- [ ] Backup download returns a valid `.sql.gz` file
- [ ] Restore upload restores DB and forces re-login redirect
- [ ] Unauthorized users (non-manager) receive 403

### Phase 3: Settings Tab UI
- [ ] Task 6: Wire "Backup & Restore" tab in `settings.html` with "Backup Now" (HTMX download) and "Restore from file" (`<input type="file">` upload), tip text about Downloads folder, RBAC-gated tab/button
- [ ] Task 7: Ensure no raw dictionaries, no stray numbers, no broken layout on /settings

### Checkpoint: UI
- [ ] Settings page renders for admin and manager with both controls working
- [ ] HTMX/Alpine tab switching intact (no `activeTab` conflicts)
- [ ] Cloud backup dashboard widget unchanged and still functional

### Phase 4: Tests + Final Verification
- [ ] Task 8: Tests for `local_backup` and `local_restore` management commands (throwaway test DB)
- [ ] Task 9: Tests for backup download and restore upload views
- [ ] Task 10: Run full existing test suite + `makemigrations --check --dry-run` + `npm run build` (if template classes changed)

### Checkpoint: Complete
- [ ] All acceptance criteria met
- [ ] Existing test suite still green (112+ tests)
- [ ] Ready for human review and approval before commit

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Restore corrupts the dev database (`eixn_pos` on localhost:5433) | High | Never run restore against dev DB; test only via `manage.py test` throwaway DB (`test_eixn_pos`) |
| `pg_dump`/`pg_restore` binary not available in container | Medium | `cloud_backup.py` already shells out to `pg_dump`; same assumption applies. Command raises clear `CommandError` if missing |
| `activeTab` Alpine conflict breaks settings tab UI | Medium | Reuse existing tab pattern exactly; verify all tabs still switch after adding backup controls |
| Restore leaves stale sessions / user invalidated | Medium | Force `logout()` + redirect to login after successful restore |
| Raw dictionaries or stray numbers render on /settings (regression from prior attempt) | Medium | No `{{ backup_list|safe }}` or raw data dumps; only structured template variables |

## Open Questions (deferred)
- Should "Backup Now" use django-q2 background task instead of sync? Deferred — sync is simpler and matches `BackupTriggerView`.
- Should the settings tab list existing local backups with per-file restore? Deferred — upload-only restore first; listing can be added later.