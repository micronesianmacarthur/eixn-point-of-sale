# Progress Log

A running log of changes made to the project, organized by date.

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
