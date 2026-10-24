# Local Backup & Restore — Task List

## Phase 1: Foundation — Management Commands

## Task 1: `local_backup` management command
**Description:** Create `backend/core/management/commands/local_backup.py` that runs `pg_dump` against the configured `DATABASE_URL`, gzips the output, writes it to `backend/backups/eixn_pos_<timestamp>.sql.gz`, and updates `last_backup.txt` marker. Mirror the `cloud_backup.py` pattern (PGPASSWORD env, subprocess, error handling).

**Acceptance criteria:**
- [x] Command exists at `backend/core/management/commands/local_backup.py`
- [x] `manage.py local_backup` produces a valid `.sql.gz` in `backend/backups/`
- [x] `last_backup.txt` is written with `last_sync`, `uploaded=false`, `local_file`
- [x] Raises clear `CommandError` if `pg_dump` not found or dump fails
- [x] Works against throwaway test DB (not dev DB at localhost:5433)

**Verification:**
- [x] `backend/.venv/bin/python manage.py local_backup` succeeds on scratch DB
- [x] `file`/`gzip -t` confirms the output is valid gzip

**Dependencies:** None

**Files likely touched:**
- `backend/core/management/commands/local_backup.py` (NEW)

**Estimated scope:** S (1 file)

---

## Task 2: `local_restore` management command
**Description:** Create `backend/core/management/commands/local_restore.py` that takes a path to a `.sql.gz` backup file, decompresses it, and runs `pg_restore` with `--clean --if-exists --no-owner --no-acl` to fully restore the database. Exits nonzero on failure.

**Acceptance criteria:**
- [x] Command exists at `backend/core/management/commands/local_restore.py`
- [x] Accepts a positional `<backup_file>` argument
- [x] Decompresses `.sql.gz` before `pg_restore`
- [x] Runs `pg_restore --clean --if-exists --no-owner --no-acl` (full restore, wipe-and-replace)
- [x] Raises clear `CommandError` if file missing, not valid gzip, or restore fails

**Verification:**
- [x] `backend/.venv/bin/python manage.py local_restore <path>` restores data on scratch DB
- [x] Integrity check: a known row exists after restore

**Dependencies:** Task 1 (pattern reference only — no code dependency)

**Files likely touched:**
- `backend/core/management/commands/local_restore.py` (NEW)

**Estimated scope:** S (1 file)

---

### Checkpoint: Foundation
- [x] `manage.py check` clean
- [x] `local_backup` produces a valid `.sql.gz` on a scratch DB
- [x] `local_restore` restores data into a scratch DB and integrity holds

---

## Phase 2: Views + URLs

## Task 3: Backup download view
**Description:** Create a Django view (in `sales/views.py`) that handles `POST`, calls `call_command('local_backup')`, and returns a `FileResponse` with `Content-Disposition: attachment` so the browser downloads the `.sql.gz`. Restricted to admin/manager via `ManagerOrAdminMixin`. On error, returns an error message (HTMX-friendly HTML or JSON).

**Acceptance criteria:**
- [x] View exists in `sales/views.py` (name: `BackupDownloadView`)
- [x] Requires login + manager-or-admin (403 for unauthorized)
- [x] Calls `call_command('local_backup')` synchronously
- [x] Returns `FileResponse` with the `.sql.gz` as attachment
- [x] On failure, returns an error response (not a 500 stack trace to the user)

**Verification:**
- [x] `POST` to the view triggers a download of a valid `.sql.gz`
- [x] Non-manager user receives 403

**Dependencies:** Task 1

**Files likely touched:**
- `backend/sales/views.py`

**Estimated scope:** S (1 file)

---

## Task 4: Restore upload view
**Description:** Create a Django view (in `sales/views.py`) that handles `POST` with `multipart/form-data` file upload, saves the uploaded `.sql.gz` to a temp file, calls `call_command('local_restore', <temp_path>)`, then logs the user out (`django.contrib.auth.logout`) and redirects to the login URL. Restricted to admin/manager.

**Acceptance criteria:**
- [x] View exists in `sales/views.py` (name: `RestoreUploadView`)
- [x] Requires login + manager-or-admin (403 for unauthorized)
- [x] Accepts uploaded file via `<input type="file">`
- [x] Calls `call_command('local_restore', <temp_path>)`
- [x] On success: `logout(request)` → redirect to `LOGIN_URL`
- [x] On failure: shows error message, does not log out

**Verification:**
- [x] Upload + restore succeeds → redirect to login (user logged out)
- [x] Invalid file → error message, user remains logged in
- [x] Non-manager user receives 403

**Dependencies:** Task 2

**Files likely touched:**
- `backend/sales/views.py`

**Estimated scope:** S (1 file)

---

## Task 5: URL routes
**Description:** Add URL routes in `sales/urls.py` for the backup download and restore upload views, under the `sales` app namespace.

**Acceptance criteria:**
- [x] `path('backup/download/', views.BackupDownloadView.as_view(), name='backup_download')`
- [x] `path('backup/restore/', views.RestoreUploadView.as_view(), name='backup_restore')`
- [x] `reverse('sales:backup_download')` and `reverse('sales:backup_restore')` resolve correctly

**Verification:**
- [x] `python manage.py shell -c "from django.urls import reverse; reverse('sales:backup_download'); reverse('sales:backup_restore')"` works

**Dependencies:** Task 3, Task 4

**Files likely touched:**
- `backend/sales/urls.py`

**Estimated scope:** XS (1 file)

---

### Checkpoint: Views
- [x] Backup download returns a valid `.sql.gz` file
- [x] Restore upload restores DB and forces re-login redirect
- [x] Unauthorized users (non-manager) receive 403

---

## Phase 3: Settings Tab UI

## Task 6: Wire "Backup & Restore" tab UI
**Description:** Replace the "Coming Soon" placeholder in `templates/core/settings.html` backup tab with working controls: "Backup Now" button (HTMX POST to `sales:backup_download` that triggers a file download), "Restore from file" (`<input type="file">` form POST to `sales:backup_restore`), tip text about the Downloads folder, and RBAC gating (tab/button visible only to admin and manager). Preserve the existing Alpine `activeTab` pattern exactly.

**Acceptance criteria:**
- [x] Backup tab shows "Backup Now" button and "Restore from file" upload control
- [x] Tip text advises moving the downloaded file from Downloads to a preferred folder
- [x] Tab and controls visible to admin and manager; hidden or 403 for others
- [x] HTMX/Alpine tab switching intact — all other tabs (General, Session, Receipt, Customers, Reports) still work
- [x] No raw dictionaries, no stray numbers, no broken layout on /settings

**Verification:**
- [x] Load `/settings/` as admin → backup tab renders with both controls
- [x] Load `/settings/` as cashier → backup tab/button not accessible (403 or hidden)
- [x] Click each other tab → still switches correctly (no `activeTab` conflict)

**Dependencies:** Task 3, Task 4, Task 5

**Files likely touched:**
- `backend/templates/core/settings.html`

**Estimated scope:** M (1 file, but UI verification is the bulk of the work)

---

## Task 7: Ensure settings page integrity
**Description:** Confirm the full `/settings/` page renders without errors for both admin and manager, with no JavaScript console errors, no broken HTMX swaps, and the cloud backup dashboard widget unaffected.

**Acceptance criteria:**
- [x] `/settings/` renders 200 for admin and manager
- [x] All tab panels render (no 500, no template errors)
- [x] Cloud backup status widget on dashboard still works (`BackupTriggerView` unchanged)

**Verification:**
- [x] Manual browser check or test client: GET `/settings/` as admin and manager
- [x] Existing `BackupTriggerView` POST still returns backup status HTML

**Dependencies:** Task 6

**Files likely touched:** None (verification only)

**Estimated scope:** XS

---

### Checkpoint: UI
- [x] Settings page renders for admin and manager with both controls working
- [x] HTMX/Alpine tab switching intact (no `activeTab` conflicts)
- [x] Cloud backup dashboard widget unchanged and still functional

---

## Phase 4: Tests + Final Verification

## Task 8: Management command tests
**Description:** Add tests for `local_backup` and `local_restore` in the appropriate app's `tests.py` (likely `core/tests.py` or a new `backup_tests.py`). Use the throwaway test DB (`test_eixn_pos`), never the dev DB.

**Acceptance criteria:**
- [x] Test that `local_backup` produces a valid gzip file
- [x] Test that `local_restore` restores data into the test DB
- [x] Test that invalid input raises `CommandError`
- [x] Tests use explicit app labels when run

**Verification:**
- [x] `manage.py test core.tests.LocalBackupTests` (or equivalent) passes

**Dependencies:** Task 1, Task 2

**Files likely touched:**
- `backend/core/tests.py` (or new test module)

**Estimated scope:** M (1-2 files)

---

## Task 9: View tests
**Description:** Add tests for `BackupDownloadView` and `RestoreUploadView` in `sales/tests.py`. Test authenticated access (admin/manager → 200/download), unauthorized access (cashier → 403), and restore flow (logout redirect).

**Acceptance criteria:**
- [x] Test backup download returns file response for admin/manager
- [x] Test restore upload logs out and redirects to login
- [x] Test 403 for non-manager users
- [x] `BusinessInfo` created in `setUp` (SetupCheckMiddleware requirement)

**Verification:**
- [x] `manage.py test sales.tests.BackupDownloadTests sales.tests.RestoreUploadTests` passes

**Dependencies:** Task 3, Task 4

**Files likely touched:**
- `backend/sales/tests.py`

**Estimated scope:** M (1 file)

---

## Task 10: Final verification
**Description:** Run the full verification suite: `manage.py check`, `makemigrations --check --dry-run`, existing test suite, and `npm run build` only if template CSS classes were added/changed.

**Acceptance criteria:**
- [x] `manage.py check` clean
- [x] `makemigrations --check --dry-run` clean (no new migrations needed — no schema changes)
- [x] Existing test suite green: `manage.py test sales core customers inventory accounting users` (112+ tests)
- [x] Cloud backup dashboard widget and `BackupTriggerView` unchanged and functional

**Verification:**
- [x] All commands above exit 0
- [x] No new migration files generated

**Dependencies:** Task 6, Task 8, Task 9

**Files likely touched:** None (verification only)

**Estimated scope:** XS

---

### Checkpoint: Complete
- [x] All acceptance criteria met
- [x] Existing test suite still green (112+ tests)
- [x] Ready for human review and approval before commit