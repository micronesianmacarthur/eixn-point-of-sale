# Progress Log

A running log of changes made to the project, organized by date.

---

## 2026-10-06

### Offline-first frontend: local Tailwind, vendored assets, teal/ink theme (`core/theming`)
- Removed every CDN tag. `cdn.tailwindcss.com` was the root problem: the till's entire UI depended
  on a shop with working internet, so a dropped connection meant an unstyled, non-interactive
  register. The Play CDN also compiles per request, and it silently ships **v3 semantics** — which
  hid the incompatibilities fixed below
- Added root Node tooling (`package.json`, `package-lock.json`, `frontend/app.css`) using the
  standalone Tailwind v4 CLI (`@tailwindcss/cli`), plus `scripts/vendor-static.mjs`. `npm run build`
  compiles and vendors, `npm run watch` rebuilds on save. The compiled stylesheet and vendored
  libraries are **committed** under `backend/static/`, so the runtime — the Alpine-based image, which
  ships no Node — needs neither Node nor network
- Vendored `htmx@1.9.12`, `alpine@3.14.8`, `chart.js@2.8.0` (pinned: the dashboard chart is written
  against the 2.x API), and a latin-subset variable Inter woff2 (~47 kB) for `font-display: swap`.
  Font Awesome needs **two** stylesheets, not one: `css/fontawesome.min.css` holds the ~1950
  `.fa-*:before { content }` glyph rules, while `css/solid.min.css` is only the `@font-face` for the
  free solid family plus `.fas { font-weight: 900 }`. Shipping `solid.min.css` alone renders every
  icon blank — they came from `all.js` before, which injects the glyphs itself. Both are linked, and
  only `fas` is used (71 icons, no `data-fa-*`), so the regular/brands webfonts stay out. The
  `format("truetype")` alternate in FA's `@font-face src` is pruned at vendor time: we ship the
  153 kB woff2, not the ~600 kB ttf, and there is no reason for a stylesheet to reference a file
  that is not there
- Theme (`frontend/app.css`): teal `brand-*` and warm-neutral `ink-*` ramps, Inter, low-contrast
  `shadow-card` / `shadow-pop`, tabular numerals on tables, shared `.card` / `.btn*` / `.field`
  components, themed flash messages, a themed login page, and an active-section highlight in the
  sidebar that the shell never had
- **Legacy scale aliases** in `@theme`: Tailwind's stock `gray` / `blue` / `red` / `green` / `yellow`
  steps are remapped onto `ink` / `brand` / the semantic ramps. ~30 templates were written against
  those names, so aliasing re-skins every interior screen at once instead of leaving them on the old
  blue-grey while only the shell is themed. New code should prefer `brand-*` / `ink-*`; the aliases
  exist so untouched templates match
- **v3 → v4 utility fixes**, found by checking every utility referenced by the templates against the
  compiled CSS (356 referenced, all present):
  - `bg-black bg-opacity-50` → `bg-black/50` in 29 modal backdrops. v4 dropped the `*-opacity-*`
    utilities, so without this every scrim would have gone fully opaque
  - `[x-cloak] { display: none !important }` moved from an inline `<style>` into the compiled sheet
    (that inline block only existed because the Play CDN could not compile it)
  - `users/login.html` had an `@apply` block inside `<style>` — only ever valid under the Play CDN,
    and dead under a compiled stylesheet. Removed, since the inputs already carry those utilities
- Added `scripts/verify-static.mjs`, run as the last step of `npm run build`, because all four of
  these failures are silent — the page still returns 200, it just arrives unstyled or with blank
  icons. It checks that no template loads a remote asset, that every `fas fa-*` icon in the
  templates has a glyph rule in the vendored Font Awesome, that every `url(...)` in a vendored
  stylesheet resolves to a file that exists, and that every utility class the templates use is
  actually present in the compiled CSS. It now passes: 47 templates, 71 icons, 590 class tokens.
  Removing one vendored font is enough to make it fail, which is the point
- Static serving in production: added `whitenoise==6.12` (`STATIC_ROOT`, middleware directly after
  `SecurityMiddleware`) because the container runs with `DEBUG=False` and had no way to serve
  `/static/` once the CDN tags were gone. Kept `StaticFilesStorage` rather than the manifest variant
  on purpose, so a missed `collectstatic` degrades to a stale sheet instead of a 500 on every page
- `docker/entrypoint.sh` now warns when `staticfiles/css/app.css` is missing after `collectstatic`,
  since that combination fails silently: 200 responses with no styling
- Cart copy: the tender button is now **Account** (was "Credit"), and everything a cashier sees in the
  cart/checkout flow that used to say "Store Credit" now says **Account** — `paymentLabel()` in the
  checkout Alpine component (which drives both the leg breakdown and the overshoot message, "Account
  cannot exceed the balance due"), the Payment Type `<select>` in `sales/partials/cart_summary.html`
  (that partial is what re-renders `#cart-panel` after every HTMX cart change, so the two panels
  disagreed after the button rename), the Refund Method `<option>` in `sales/checkout.html`, and the
  two "Select a customer before adding store credit." validation strings, and the dashboard's violet
  card — title "Store Credit / Owner", its "Credit:" sub-line (now "Account / Owner" / "Account:",
  matching the Cash and Card cards beside it), plus the payment-pie legend so the same bucket is not
  called two different things on one screen. The rationale from the till: "Store credit" reads as
  loyalty points the shop owes the customer. The enum value `STORE_CREDIT` is unchanged everywhere —
  this is a label-only change. Remaining "Store Credit" labels: `zreport_content`,
  `session_close`, and `sales/offline_recovery.html`
- `.gitignore`: `node_modules/` and `backend/staticfiles/`
- Verified in production mode (`DEBUG=False`, assets via WhiteNoise) that `/login/`,
  `/sales/dashboard/`, `/sales/checkout/`, `/inventory/` and `/customers/` render with **zero
  external references**, that every asset referenced from the HTML *and from inside the
  stylesheets* (fonts) returns 200, and that the served Font Awesome CSS carries its 1950 glyph
  rules. `manage.py check` clean (the previous
  `staticfiles.W004` warning is gone now that `backend/static` exists), `makemigrations --check`
  clean, `sales inventory` 98 tests pass, full suite 110 tests with only the 4 documented
  `users.tests.UserManagementDeleteTests` baseline failures

## 2026-10-05

### Product soft-delete: archive instead of hard delete (`inventory/delete-product`)
- Replaced the hard delete with a soft delete. Every FK to `Product` is `PROTECT`, so `Delete` only
  ever worked for a product that had never been received, sold, counted or bundled — in a real shop,
  almost nothing. `ProductDeleteView` now sets `is_active=False` and keeps the row, which is what
  receipts, sale history and reports actually need it for
- Added `Product.is_active` (migration `inventory/0011_product_is_active.py`) plus
  `ProductQuerySet.active()` / `.archived()`. The default manager is deliberately **not** filtered:
  a filtered default manager would silently hide archived products from history and reports, so every
  interactive query opts in explicitly instead
- Hidden on interactive screens: product list and its HTMX partial (behind a new "Show archived"
  filter), checkout search, quick service picks, cart insertion, bundle payloads, low-stock panels and
  counts, dashboard product count, receive selection and search, purchase-order item add, repack
  search and parents, bundle component search, offline-recovery lookup
- Kept visible where history demands it: the inventory report still values archived stock, the
  product detail page still resolves (with an "is archived" banner), and sale/receipt screens are
  untouched. The count sheet is the deliberate exception — it writes stock, so it only offers
  active products, while the inventory report reads through `include_archived=True`
- Restore path: the product edit modal gained an "Active (sellable)" checkbox, the archive button
  became "Archived", and Django admin gained `is_active` in `list_display`/`list_filter` plus
  `archive_selected` / `restore_selected` actions (the blanket `delete_selected` action was dropped,
  since it can still hit the same `PROTECT` errors)
- Added server-side gates, because search filtering is bypassable by a stale page or a crafted POST:
  `process_checkout` names the offending products instead of raising `KeyError`; `post_stock_count`,
  `receive_inventory` and `execute_repack` raise `ValueError`; the receive, repack, PO and bundle
  views resolve posted ids with `is_active=True`; `batch_offline_recovery` rejects archived ids
  *before* creating its virtual session
- `CheckoutView._prune_archived_cart()` drops cart lines whose product was archived mid-sale and tells
  the cashier, so an archived item neither renders nor reaches the posted cart. Returns are
  unaffected: they go through `process_return`, so a discontinued product can still be refunded
- `bulk_seed_products_csv` now reports a per-row error when a submitted SKU already exists (with an
  extra hint when it is archived) instead of letting `bulk_create` raise `IntegrityError` — archiving
  keeps the unique SKU row that a hard delete used to free
- Fixed a pre-existing bug in `CartAddView` surfaced by the new cart tests: it stored
  `product.stock_quantity` (a `Decimal`) in the session, which the JSON-serialising session backend
  rejects, so every add-to-cart POST returned 500. Stock is now stored as a `float`
- Tests: `ProductArchiveTests` (18 cases: queryset split, archive-not-delete including with receipt
  history, idempotent re-archive, manager-only, restore via the edit form, hiding on list/table/
  count/receive/repack-search, report still valuing archived stock, and rejection by every
  stock-writing path) and `ArchivedProductSalesTests` (11 cases: search, cart add, stale-cart prune,
  `process_checkout`, the checkout POST, offline recovery, bundles, and history of a product archived
  after it was sold). `manage.py test` runs 110 tests: 106 pass, with only the 4 documented baseline
  failures in `users.tests.UserManagementDeleteTests`
- Verified with `manage.py check` (only the pre-existing `staticfiles.W004` for the missing
  `backend/static`) and `makemigrations --check --dry-run` (no drift). The migration is a plain
  `AddField`, so it is fully exercised by the test database; it has **not** been applied to the dev
  database
- Not committed: `count_entry.html` still carries an unrelated change from earlier (removal of a
  duplicate bottom "Preview Changes" button) that should go in its own commit

---

### Merged `sales/split-payment` into `main`
- Merged the split-tender-at-checkout feature branch into `main` with `--no-ff` (merge commit
  `ecd5ea6`) and deleted the branch, per the Git workflow in `AGENTS.md`
- Verified the dev database was already compliant with the split-payment schema before merging:
  `sales` `0007`–`0009` all applied, the legacy `payment_type`/`payment_amount` columns already
  dropped, and `manage.py migrate` reports "No migrations to apply". The `0008_backfill_payments`
  backfill had preserved every split tender — each transaction's `Payment` rows sum to its
  `total_amount` — so no data repair was needed
- Took a `dumpdata` backup to `/tmp/opencode/eixn_dump_premerge.json` before touching the dev
  database, as `AGENTS.md` requires for migrations run against real data
- Post-merge `manage.py check` is clean and the suite still shows only the 4 documented baseline
  failures in `users.tests.UserManagementDeleteTests` (missing `BusinessInfo` → 302 to `/setup/`)
- Corrected the branch-naming convention in `AGENTS.md`: feature branches are `<app>/<name>`
  (e.g. `sales/split-payment`), not `feature/<name>`, matching how branches are actually named

---

### Dashboard: voided sales no longer counted as revenue
- Fixed the dashboard "today" revenue card, which aggregated **every** transaction for the day
  regardless of status — so a voided sale kept inflating both the revenue total and the transaction
  count. `DashboardView` now excludes `status=VOIDED`, matching what the monthly card, the 30-day
  chart, the by-clerk table and the weekly comparison already did
- Fixed the same omission in the dashboard top-product query, which counted the line items of voided
  transactions (it also bypasses the `get_top_products()` helper that already filters on `POSTED`)
- Pre-existing bug, present on `main` unchanged; found via the dashboard, not introduced by any
  other work
- Added `DashboardVoidExclusionTests` in `sales/tests.py` (previously an empty file): revenue,
  transaction count and top product all ignore a voided sale; an all-void day reports zero instead
  of crashing on `None`; posted sales are still counted, guarding against over-filtering; and voiding
  a sale from another day leaves today's figures untouched
- Confirmed the tests genuinely catch the bug — reverting the fix fails the 4 bug-specific tests while
  the 2 guard tests keep passing

---


### Split Payment at Checkout
- Replaced the single `payment_type`/`payment_amount` pair on `Transaction` with a new `Payment` model:
  one row per tender per transaction, constrained by `unique_payment_type_per_transaction`
- Added `sales` migrations `0007_payment`, `0008_backfill_payments` (converts every legacy transaction
  into one `Payment`, skipping zero-amount rows) and `0009_remove_transaction_payment_fields`;
  verified the forward and reverse paths against a real pre-split schema, so a rollback restores the
  original scalar values
- Checkout now accepts several tenders in one sale: Cash, Card and Store Credit may be combined, and
  pressing an already-used tender type adds to that leg instead of creating a second one
- Split payment **must cover the sale** — no unpaid balance or store tab is created. Only cash may
  over-tender, and the over-payment is returned as change; the keypad now fills the amount box
  instead of completing the payment outright
- Client-sent `payments_json` is treated as untrusted: `process_checkout` recomputes the total from the
  products and re-validates every leg. A missing or unparseable payload falls back to a single
  full-price tender so plain single-tender sales keep working
- Store credit requires a customer, and the credit limit and `cached_balance` now consider only the
  credit leg; loyalty points accrue on the non-credit portion
- Returns remain single-method, and a refund to store credit may drive `cached_balance` negative;
  reversal follows the chosen refund type
- `close_session` expected-drawer cash was reworked: cash tender minus change on sales, refunds
  subtracted, owner draws excluded, and card/credit sales contributing nothing to the drawer
- Receipts (thermal and on-screen) print one line per tender plus change, and the old `PAID`
  summary line is gone; the transaction and customer detail pages show the same breakdown
- `reconcile_customer_balances` and `fix_customer_credit_balances` now derive balances from signed
  store-credit `Payment` rows
- Tests: 44 service-level split-payment tests, plus 7 new request-level tests covering the checkout
  page, the `payments_json` payload, server-side underpayment rejection, the fallback path, and the
  receipt / transaction-detail / customer-detail templates. `manage.py test sales accounting inventory
  customers` is green (77 tests — 51 split-payment plus the 6 dashboard tests merged in from `main`,
  and 20 in the other three apps)
- Note: the 4 failures in `users.tests.UserManagementDeleteTests` are pre-existing and unrelated —
  they reproduce identically with these changes stashed. Root cause: that test class never creates a
  `BusinessInfo` row, so `SetupCheckMiddleware` 302-redirects every request to `/setup/` (see the
  gotcha in `AGENTS.md`). Adding `BusinessInfo.objects.get_or_create(business_name='Test Shop')` to
  its `setUp` makes all 4 pass; verified, but left untouched here as it is outside this change.

### Checkout UI follow-up
- Removed a duplicated **Complete Sale** button in `sales/checkout.html` (two byte-identical blocks
  had been left stacked one under the other); there is now exactly one
- Removed the auto-submit in `base.html:469` that fired as soon as the tendered legs reached or
  exceeded the subtotal. Reaching the full total is no longer treated as consent to post — the sale
  only completes when the cashier clicks **Complete Sale**
- Because underpayment is now normally discovered by clicking that button, `tenderError` became a
  message string rather than a boolean flag, so each rejection says what actually went wrong:
  no amount entered, no tender added, tendered `$X` short of the `$Y` due, or a non-cash leg that
  would exceed the balance due (change is cash-only)
- Cash over-tender still shows the change modal, but only after the click — confirming the modal
  remains the second, deliberate confirmation step rather than something that appears on its own
- Verified by executing the Alpine `posCart()` object in Node against 21 assertions covering
  no-auto-post, click-to-post, the underpayment message, the change-modal path, card-overshoot
  rollback, split legs, repeat-tender merging, and the Enter-key path. `manage.py test sales` is
  green (51 tests); full suite unchanged at 4 pre-existing `users` failures

### Complete Sale disabled until the sale is covered
- **Complete Sale** is now disabled unless the tenders cover the subtotal, so the button can no longer
  be pressed to post an incomplete sale. `canSubmit` (`base.html`) requires a non-empty cart, at least
  one tender leg, and `remaining <= 0.004`
- Note that `remaining` is `0` for an empty cart, so the coverage test alone would have wrongly
  enabled the button — hence the explicit `items.length > 0` term
- Disabled styling via Tailwind's `disabled:` variants, plus `disabled:hover:bg-blue-600` so the
  button does not still darken on hover and look clickable
- A disabled button with no explanation reads as broken, so a `submitHint` line appears under it
  naming what is missing (empty cart, no payment method, or the exact shortfall). The button is never
  disabled on the return path, where the single refund method makes tender logic inapplicable
- The underpayment guard inside `submitCheckout()` is kept as defence in depth: it is now unreachable
  through the UI, but it is the last line of defence if the client logic and the button ever diverge
- Verified by executing `posCart()` in Node against 30 assertions, including the exact
  `:disabled="!isReturn && !canSubmit"` binding for both sale and return paths, split tenders
  enabling only on the final leg, one-cent-short staying disabled, and leg removal re-disabling.
  Full suite unchanged at the 4 pre-existing `users` failures

---

## 2026-09-30

### README — Installation & Business Configuration
- Wrote `README.md` (was empty) covering prerequisites, local installation via `uv sync` + `make build`,
  running the server **and** the django-q2 `qcluster` worker (receipts do not print without it),
  Docker Compose deployment (`make up`/`deploy.sh`), and a full business-configuration section
- Documented the fresh-clone gotcha that caused the `make build` failure: `backend/.env` is git-ignored
  and `DATABASE_URL` has no default, so every `manage.py` command aborts until
  `cp .env.example .env` is run
- Documented business setup in two layers: environment variables (DB, printer/cash drawer, S3 backup)
  and in-app settings (`/setup/` `BusinessInfo` wizard, `/settings/` `SystemSetting` rows, roles/permissions,
  inventory ordering, open/close session flow, customer credit)
- Recorded fixed behaviours explicitly: `TIME_ZONE` is `Pacific/Pohnpei`, money is `Decimal` with
  `ROUND_HALF_UP`, and there is **no** tax, currency, or receipt-footer configuration
- Added a troubleshooting section and a Make-target reference table

---

## 2026-09-12

### Barcode Scanner + Network Printer + Cash Drawer (SRS §3.2)
- **Barcode scanner protocol** (`templates/base.html`, global):
  - Listener captures the F12…ENTER keystroke envelope used by USB scanners regardless of which field has focus
  - On F12: enters scan mode, buffers subsequent printable characters, ignores modifiers
  - On ENTER: injects the scanned value into `#product-search`, fires `input` + `keyup` so the HTMX `keyup changed delay:300ms` trigger runs, returns focus to the search box
  - ESC cancels a partial scan; non-scan typing is untouched
- **Network printer wiring**:
  - Added `PRINTER_HOST`, `PRINTER_PORT` (default 9100), `PRINTER_CASH_DRAWER` (default true) to `core/settings.py`, `.env.example`, `.env`, and docker-compose (moved to the qcluster service which executes the task; also added to web)
  - New task `core/tasks.print_receipt(txn_id)` — loads the Transaction, calls `build_receipt_lines`, streams it (UTF-8 + CRLF) to `PRINTER_HOST:PRINTER_PORT` over TCP with a 5s timeout; gracefully no-ops when no host is configured
  - `CheckoutCompleteView.post` fires `async_task('core.tasks.print_receipt', txn.id)` after both sale and return completion (django-q2), keeping the responder fast; on-screen receipt remains as fallback
  - Kept `async_print_receipt(lines, …)` as a legacy wrapper around the same socket logic
- **Cash drawer kick**: ESC/POS opener `\x1B\x70\x00\x19\xFA` (`CASH_DRAWER_KICK` = `1b700019fa`) is appended to the print job on every sale/return when `PRINTER_CASH_DRAWER` is enabled; testable with `nc -l 9100`
- Removed dead `build_receipt_lines` import from `sales/views.py` (now only used inside the task)
- Verified: `manage.py check` clean; sales + inventory test suites (12 tests) pass; `print_receipt(999999)` returns `skipped` when `PRINTER_HOST` is unset (dev default). Pre-existing `users` delete-test failures (4) reproduce identically on main — unrelated to this change

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
