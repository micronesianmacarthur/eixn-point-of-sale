# Statement of Intent: Local Backup & Restore (eixnPOS)

## Outcome
A local backup/restore feature in the eixnPOS settings "Backup & Restore" tab:
- **Backup Now:** runs `pg_dump` server-side and downloads a `.sql.gz` file to the browser's Downloads folder, with tip text reminding the user to move it to their preferred folder.
- **Restore from file:** uses `<input type="file">` to upload a backup file, then the server runs `pg_restore` for a full database restore.

## User
Admin and manager roles only.

## Why now
Revisiting local backup after previous attempts broke the settings UI — raw dictionary dumps rendered to the page, a button that did nothing, and numbers rendering all over /settings.

## Success
- Backup Now downloads a valid `.sql.gz`.
- Restore from file fully restores the database from an uploaded file.
- Settings page UI stays intact (no raw data dumps, no broken layouts).
- Works across browsers (download fallback when `showSaveFilePicker` isn't available).

## Constraint
Browser file-system limits: no arbitrary destination path picking (downloads go to Downloads; user moves file manually). Server-side `pg_dump`/`pg_restore` in a Django web app. Must not break existing cloud backup or dashboard widget.

## Out of scope
Cloud/S3 backup changes, arbitrary destination folder selection, selective table restore, backup scheduling automation.