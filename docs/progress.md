# Progress Log

A running log of changes made to the project, organized by date.

---

## 2026-09-11

### Shipping Blockers — Branch `fix/shipping-blockers`
- Fixed Docker build/entrypoint wiring (`docker/Dockerfile`, `docker-compose.yml`, `docker/entrypoint.sh`):
  - Build context changed from `./backend` to repo root; Dockerfile now `COPY backend/` and copies `docker/entrypoint.sh` to `/usr/local/bin/docker-entrypoint.sh`
  - Old ENTRYPOINT referenced a `docker-entrypoint.sh` that never existed (containers could not boot)
  - Entrypoint now execs an overridden command (e.g. `manage.py qcluster`) so web and qcluster services behave correctly
- Added `.dockerignore` (excludes `.venv`, git, sqlite db, media, secrets from build context)
- `deploy.sh`: removed `--volumes` from `docker system prune` — was a data-loss risk for the `pgdata` volume
- Wired receipt display into checkout (`sales/views.py`, new `sales/receipts.py`, `templates/sales/receipt.html`):
  - New `build_receipt_lines(txn)` formats a 40-column ESC/POS plain-text receipt (for future network-printer use)
  - On-screen receipt page (`/sales/receipt/<id>/`) now shown after every completed sale and return
  - Confirmation below the receipt: "Print Small Receipt" (80mm thermal) or "Print Full Page (Letter)" via `window.print()` with format-specific CSS
  - "New Sale" link returns to checkout
### Settings Page — Reports Tab
- Added "Reports" tab to system settings page (`templates/core/settings.html`), placed between Customers and Backup &amp; Restore
- Alpine `activeTab` state extended (`reports`); panel currently a "Coming Soon" placeholder pending actual report settings

### Sales Management Page — Fill-Height Scrollable Table
- `#sale-table` now fills the remaining height of its parent and scrolls internally (`templates/sales/sale_list.html`, `partials/sale_table.html`)
- Page content wrapped in `md:flex md:flex-col md:h-full` (fills the `flex-1 overflow-y-auto` base wrapper); table is `md:flex-1 md:min-h-0` with an `overflow-auto min-h-0 flex-1` viewport
- Header row pinned via `sticky top-0 bg-gray-50` while scrolling
- Responsive: fixed-height fill only ≥768px (`md:`); on mobile the page scrolls naturally with horizontal table scroll preserved
- Filter form now uses `hx-swap="outerHTML"` so HTMX swaps replace the whole `#sale-table` (no nested duplicate ids); partial mirrors the same structure

### Top Items Panel — Fixed Height + Scroll
- Panel body now capped at ~4 item rows (`max-h-60`) with `overflow-y-auto` scrolling
- Column headers stay pinned via `sticky top-0` while scrolling within the panel

### Top Items Panel — Time Range Selector
- `TopProductsView` (`sales/views.py`) replaces `TopProductsTodayView`; accepts `?range=today|week|month|all` (unknown values fall back to `today`)
- Week = last 7 days, Month = last 30 days, All = no date filter
- `get_top_products()` (`sales/analytics.py`) now treats `start_date`/`end_date` as optional (skips the date filter when `None`)
- `top_products.html` partial gained a segmented Today / Last 7 Days / Last 30 Days / All Time control; buttons re-fetch the panel via HTMX (`hx-target="#top-products-panel"`)
- Endpoint renamed `top_products_today` → `top_products`; `dashboard.html` updated accordingly

### Backup Badge — 24h Staleness
- Added `_backup_is_stale()` (`sales/views.py`): true when the marker timestamp is missing/unparseable or older than 24 hours
- Badge state priority is now: **Not backed up** (red, stale >24h) &rarr; **Synced** (green) &rarr; **Upload Pending** (yellow) &rarr; **Not Configured** (gray)
- Stale state also adds a warning line under the badge ("Last backup is over 24 hours old")

### Backup Status — Honest Badge State
- The dashboard "Synced" badge was triggered by any local dump (`last_backup.txt` marker), even with `--no-upload` and zero S3 config
- `cloud_backup` now writes a JSON marker `{"last_sync", "uploaded", "local_file"}`; `uploaded` is only true after a successful S3 upload
- `_read_backup_status()` (`sales/views.py`) parses the JSON and falls back to the legacy plain-text marker
- Badge states: **Synced** (uploaded) / **Upload Pending** (local-only dump, shows the local filename) / **Not Configured** (no marker)
- The dashboard "Backup Now" button still creates a local snapshot only (`no_upload=True`) and now honestly reports it as pending

### Cloud Backup Scheduling
- New `core/tasks.run_cloud_backup()` wrapper around the `cloud_backup` command (no-ops without S3/PostgreSQL)
- New `core/management/commands/ensure_backup_schedule.py` idempotently creates the daily django-q2 `Schedule` (23:30 local)
  - `docker/entrypoint.sh` calls `ensure_backup_schedule` after `migrate`
  - Restored the real backup status widget on the dashboard (`sales/partials/backup_status.html`) — was a "Coming Soon" stub
  - `boto3` confirmed already present in `backend/pyproject.toml`

---

## 2026-09-10

### Dashboard — Online Backup Card
- Updated `backend/templates/sales/partials/backup_status.html`
- Replaced interactive backup card (status badge + "Backup Now" button) with a static "Coming Soon" placeholder
- Backend infrastructure (`cloud_backup` command, `BackupTriggerView`, boto3) remains intact but disabled in the UI

### Future Features Documentation
- Created `docs/future-features.md` to track deferred features
- Logged Online Backup (Cloud Backup Sync) as "Coming Soon"
- Logged Loan Management Module with summary of the full implementation plan from `docs/loan-feature-plan.md`

### Project Cleanup
- Created `docs/` directory
- Moved 10 loose `.md` files from project root into `docs/`
- `README.md` remains at root per convention

### Settings Page — Customers Tab
- Added "Customers" tab to system settings page (`core/views.py`, `templates/core/settings.html`)
- New setting: `DEFAULT_CUSTOMER_CREDIT_LIMIT` — configurable credit limit for new customers
- Settings page now uses Alpine.js tabbed layout (General, Session, Customers)
- Seeded default value `0.00` via migration `core/migrations/0005_seed_default_customer_credit_limit.py`
- Customer creation form (`customers/customer_list.html`) now pre-fills credit limit from this setting
- `CustomerListView` updated to pass `default_credit_limit` to template context

### Settings Page — Input Styling
- Added `border border-gray-300` and focus ring classes to all form inputs in `SettingsForm` (`core/views.py`)
- Affects markup rate, session timeout, and default credit limit fields

### Settings Page — Backup & Restore Tab
- Added "Backup &amp; Restore" tab to system settings page (`templates/core/settings.html`)
- Contains a "Coming Soon" placeholder — functionality deferred to a future version

### Offline Recovery — Product Lookup Panel
- Added searchable product lookup panel to the right of the offline recovery grid (`templates/sales/offline_recovery.html`)
- `OfflineRecoveryView` now passes `products_json` (id, sku, name) to context (`sales/views.py`)
- Panel lists product names + product_id; clicking an item appends `id:1` to the current row's items field
- Edited `offlineGrid()` Alpine component: added `products`, `productSearch`, `filteredProducts`, and `appendProduct()`
- Reworked layout to flex: recovery card keeps original `max-w-5xl` width, lookup panel (`lg:flex-1`) fills the remaining space

### Offline Recovery — Submit Bug Fix
- Fixed `json.JSONDecodeError` on submit (`Expecting value: line 1 column 1 (char 0)`)
- Root cause: view read `request.body` (raw urlencoded form data) but the hidden form sends JSON in a `body` form field
- `OfflineRecoveryView.post` now uses `json.loads(request.POST.get('body') or '{}')` (`sales/views.py`)

### Offline Recovery — Mobile Layout Fix
- Fixed product lookup panel overflowing to the right on mobile
- Switched from flex to `xl:grid-cols-[minmax(0,52rem)_minmax(0,1fr)]` with `min-w-0` on both panels; stacks vertically below `xl`, lookup fills remaining width on desktop, table wrapper constrained to full width
- Moved two-column breakpoint from `lg` (1024px, iPad landscape) to `xl` (1280px) and reduced recovery column cap to 52rem so both panels always fit

### Customer Detail — Edit Button
- Added `Edit` button at top-right of customer detail page (`templates/customers/customer_detail.html`), manager-only
- Replicated the Alpine edit modal from `customer_list.html` (pre-filled with customer values); submits to `/customers/{id}/edit/`

### Inventory Count Sheet + Stock Adjustments (audit trail)
- New printable **Inventory Count Sheet** at `/inventory/report/` (staff-readable):
  - Filters: search (name/SKU), vendor, category, and Price/unit toggle (retail or cost)
  - Print header shows business name, printed date/time, filter scope, and valuation type
  - Table lists stockable products (excludes services, variable-weight, N/A SERVICE vendor) with `#`, ID, SKU, Description, Price/unit, Price (total), Stock avail, and blank Stock actual for write-ins
  - "Post Count" and "Adjustments Log" buttons appear for managers; "Print Count Sheet" for everyone
- Manager-only **Count Entry** page at `/inventory/count/`:
  - Same table with editable Stock actual inputs (prefilled with system stock) and per-row Reason select (Physical count, Damaged goods, Expired, Found on shelf, Shrinkage, Other)
  - Note field for count reference; "Preview Changes" shows a summary of just the changed rows with old→new→delta and cost-value impact; editable via anchor
  - "Post N Adjustment(s)" sends a final POST to `/inventory/count/post/` which atomically applies the count via `inventory.services.post_stock_count`
- **Audit trail** at `/inventory/adjustments/` (manager-only):
  - Dated log with Date, Count# (COUNT-id), Product (name+SKU), Previous, Actual, Delta, Reason, Cost value, By; delta and cost cells colored by sign
  - Summary cards: total adjustments, net units, net cost value; filter by COUNT#
- **New models** (`inventory/models.py`, migration `0010`):
  - `InventoryStockCount` — created_by, note, status (DRAFT/POSTED), created_at, posted_at
  - `InventoryAdjustment` — stock_count (nullable), product, previous_qty, adjusted_qty, delta, reason, cost_price_at_adjustment (snapshot), delta_cost_value, adjusted_by, created_at
- Atomic posting service (`inventory/services.py:post_stock_count`): uses `select_for_update` to lock products, computes delta and cost snapshot at post time, skips equal rows, deletes draft count when nothing changed, or raises `ValueError` on negative counts
- Navigation: "Count Sheet" link added to Management sidebar; "Stock Adjustments" added to System sidebar (manager-only); "Count Sheet" and "Stock Adjustments" buttons added to the Inventory list toolbar (manager-only)
- Tests: report lists only stockable products; cost valuation correct; count/adjustment pages block non-managers; post_stock_count updates stock + writes audit rows; same-values produce no count; negative counts rejected; empty items rejected; POST view updates stock end-to-end
