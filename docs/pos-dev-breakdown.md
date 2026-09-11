# 🏗️ Enterprise Point of Sale (POS) System Architecture & Blueprint

### Architecture Engine: Django Monolith + Service Layer Architecture (Pre-Optimized for React/Vue V2 Migration)

### Environment & Package Matrix: Astral `uv` + Docker (Multi-stage Build Engine)

### UI Matrix: Tailwind Dashboard Template

---

## 📌 Architectural Blueprint Design Principles

* **The Service Layer Rule:** To ensure a future V2 frontend rewrite (React/Vue) requires zero backend rebuilding, **all business logic must live in pure Python service functions (`services.py`)**, completely detached from standard Django views. Views act merely as traffic routing controllers.
* **The Transactional Cached Engine:** To prevent massive **O(N)** database lag, customer outstanding debt is **never** calculated dynamically from all historical transactions. Instead, ledgers utilize cached, materialized fields that are strictly updated via atomic service-layer transactions, guaranteeing instant read performance (**O(1)** read complexity).
* **The Shared-Register Multi-User Lifecycle:** Registers utilize a shared session state. Any validated employee can execute transactions under an active session, while individual accountability is preserved via immutable audit footprints on every transaction.
* **Modern Python Tooling:** Development, locking, and dependency management use Astral `uv` instead of standard `pip` and `requirements.txt`. This ensures lightning-fast environment builds inside Docker and absolute reproducibility using a native `uv.lock` workflow.
* **Strict Corporate Veil:** Business operational finances and owner capital injections are strictly decoupled into isolated ledgers to maintain GAAP compliance and pristine audit trails.
* **Fail-Safe Integrity (Multi-Layer Guardrails):** Financial state integrity is protected by a defense-in-depth model: Database-level constraints prevent accidental credit exposure, while automated background reconciliation routines flag any cache-to-ledger anomalies.

---

## 🗺️ Master Micro-Task Roadmap

### 📦 Phase 1: Environment Orchestration via Astral `uv` & Core Scaffolding

* [ ] **1.1 Directory Structure:** Establish the core project layout:
```text
eixn-pos/
├── backend/          # Django Source Project Base
│   ├── pyproject.toml # Project configuration managed by uv
│   └── uv.lock       # Cryptographically pinned dependency lockfile
├── docker/           # Environment Manifest Configurations
│   └── Dockerfile    # Multi-stage uv build instructions
└── docker-compose.yml

```


* [ ] **1.2 Environment Manifest (`docker/Dockerfile`):** Write a multi-stage Python 3.12 alpine build configuration that leverages `ghcr.io/astral-sh/uv:latest` to compile and synchronize dependencies.
* **Build Stage:** Use `uv sync` to build the environment, installing essential system dependencies (`gcc`, `postgresql-dev`, `musl-dev`).
* **Runtime Stage:** Copy the lightweight virtual environment (`.venv`) into a clean production alpine image to keep container sizes minimized.


* [ ] **1.3 Service Orchestration (`docker-compose.yml`):** Define a dual-container architecture:
* `db`: Running `postgres:16-alpine` mapping internal data to a local named Docker volume.
* `web`: Building your custom Python container via the `uv`-driven Dockerfile, exposing port **8000**, binding your local `backend/` directory as a working directory volume, and linking structural dependency to the `db` layer.


* [ ] **1.4 Project Bootstrapping:** Initialize the workspace using `docker-compose run --rm web uv run django-admin startproject core .` to scaffold the project files using the virtual environment.
* [ ] **1.5 Database Adaptor Routing:** Integrate the C-optimized database adapter via `uv add django psycopg environs`. Configure `core/settings.py` to route database connections via an atomic connection string parsed from environmental configurations.
* [ ] **1.6 Modular App Scaffolding:** Execute `uv run manage.py startapp` to establish five separate internal domains: `users`, `customers`, `inventory`, `sales`, and `accounting`.

---

### 👥 Phase 2: Custom Authentication & Granular Access Boundaries

* [ ] **2.1 Extended User Schema (`users.models.User`):** Subclass Django's default `AbstractUser`. Define a strict, immutable string-choice selection enum (`TextChoices`) representing roles: `CASHIER`, `MANAGER`, and `ADMIN`. Set the absolute default role to `CASHIER`.
* [ ] **2.2 Encapsulated Permission Layer:** Append optimization property routines directly to your User schema for rapid verification:
* `is_cashier` (True if user role is `CASHIER`, `MANAGER`, or `ADMIN`)
* `is_manager` (True if user role is `MANAGER` or `ADMIN`)
* `is_admin` (True if user role is `ADMIN`)


* [ ] **2.3 Engine Registration:** Inject `AUTH_USER_MODEL = 'users.User'` inside `settings.py` before executing initial structural migrations.
* [ ] **2.4 Session Gatekeeping UI:** Craft secure backend views mapping authentication workflows (secure login forms, session invalidation routines) styled neatly inside your Bootstrap template canvas.
* [ ] **2.5 Administrative Identity Board:** Design a dedicated User Management view restricted explicitly via code wrappers to `ADMIN` or `MANAGER` profiles. This screen manages user creation, role changes, and profile security parameters. Include inline **Edit** button per row (visible only to manager/admin) linking to a dedicated `UserUpdateView`. The **Create User** button opens an inline modal form rather than a separate page.

---

### 💳 Phase 3: Customer Profiles & The Transactional Debt Engine

* [ ] **3.1 Open Ledger Schema (`customers.models.Customer`):** Construct fields for `name`, `phone`, `email`, `allow_pay_later` (Boolean, default=False), `credit_limit` (Decimal, default=0.00), `is_owner` (Boolean, default=False), and a **`cached_balance`** (Decimal, default=0.00).
* [ ] **3.2 Database-Level Guardrails (Safety Constraints):** Add a `CheckConstraint` inside the `Customer` model metadata (`class Meta`) to guarantee that `cached_balance` can never exceed `credit_limit` for standard clients, acting as a final database firewall:
```python
constraints = [
    models.CheckConstraint(
        check=models.Q(is_owner=True) | models.Q(cached_balance__lte=models.F('credit_limit')),
        name='check_credit_limit_boundary'
    )
]

```


* [ ] **3.3 Atomic Balance Management:** Ensure that `cached_balance` is never modified directly by views. It must strictly be adjusted within `services.py` atomic blocks during purchases, payments, or equity draws to eliminate data drift hazards.
* [ ] **3.4 Credit Validation Rules:** Implement a structural model method `has_available_credit(amount)` returning a Boolean truth statement:
* If `is_owner == True`: Bypass limit checks entirely and return `True` (unlimited store equity access).
* Else: Return `True` only if $(\text{cached\_balance} + \text{Proposed Amount}) \le \text{credit\_limit}$.


* [ ] **3.5 Account Ledger Interface:** Build a comprehensive Customer Management dashboard using your Bootstrap template. This must present a scrollable ledger statement showing all historical purchases alongside the instantly readable, pre-aggregated `cached_balance`. Include a **New Customer** button (visible only to manager+) that opens an inline modal form with name/phone/email/credit_limit/allow_pay_later/is_owner/loyalty_enabled fields, posting to a dedicated `CustomerCreateView`. Each row has an **Edit** button (visible only to manager+) linking to a dedicated `CustomerUpdateView` on a full-page form.

---

### 📦 Phase 4: Dynamic Inventory Controls & Capital Accounting

* [ ] **4.1 Core Product Foundations (`inventory.models`):** Construct two primary entities:
* `Vendor`: Name, primary contact agent, active phone, operational email.
* `Product`: Relational link to `Vendor`, unique SKU/Barcode token string, name, static `cost_price`, static `retail_price`, optional `discount_price`, an active `is_on_sale` boolean flag, `stock_quantity` integer, and a `min_stock_level` monitoring threshold.
* Include a **New Product** button (visible only to manager+) on the product list page that opens an inline modal form with SKU/name/vendor/pricing/stock fields, posting to a dedicated `ProductCreateView`.
* Build a dedicated vendor list page (`VendorListView` + `VendorCreateView`) at `inventory/vendors/` with a paginated table (Name, Contact, Phone, Email, #Products) and a manager-gated **New Vendor** inline modal. Add a "Vendors" link to the sidebar between Customers and Inventory.

* [ ] **4.2 Back-Office Capital Schema (`accounting.models.OwnerCapitalLedger`):** Create an isolated model to track owner equity transfers cleanly away from daily register flows: `owner_user_id`, `amount`, `transaction_type` (Enum: `CONTRIBUTION`, `DRAW`), `reference_receipt_id`, and `timestamp`.
* [ ] **4.3 Procurement Logs (Purchase Orders):** Author a dual-tier schema framework:
* `PurchaseOrder`: Relational `Vendor` link, tracking pointer to creator `User`, operational timestamp, and operational tracking flags (`DRAFT`, `SENT`, `RECEIVED`, `CANCELLED`).
* `PurchaseOrderItem`: Link to parent `PurchaseOrder`, relational `Product` link, and designated order count target.
* Include a **New Purchase Order** button (visible only to manager+) on the purchase order list page that opens an inline modal form with vendor selection, posting to a dedicated `PurchaseOrderCreateView`.


* [ ] **4.4 Inbound Stock Verification (Inventory Receipts):** Author a dual-tier logging schema:
* `InventoryReceipt`: Nullable tracking link back to originating `PurchaseOrder`, direct `Vendor` anchor, recording pointer to receiver `User`, execution timestamp, an equity tracking boolean flag (`funded_by_owner`), and total consolidated transaction cost.
* `InventoryReceiptItem`: Link to parent `InventoryReceipt`, targeted `Product` link, physical count validated on delivery, and historical `cost_price_at_receiving` snapshot.



---

### 🛒 Phase 5: The Sales Engine & Shared Session Lifecycle

* [ ] **5.1 Shared Register Session Schema (`sales.models.Session`):** Define the operational shift parameters:
* `opened_by`: Link to the initiating `User`.
* `closed_by`: Link to the closing `User` (Nullable).
* `start_time` / `end_time`.
* `starting_cash` (Decimal balance put in the drawer).
* `ending_cash_expected` / `ending_cash_actual`.
* `status`: Active processing flag choices (`OPEN`, `POSTED`).


* [ ] **5.2 Master Checkout Schema:** Define the primary sales logging layers:
* `Transaction`: Linked to the active operational `Session`, nullable tracking link to client `Customer`, total invoice amount (`total_amount`), payment type enum (`CASH`, `CARD`, `STORE_CREDIT`, `OWNER_DRAW`), status flag (`DRAFT`, `POSTED`, `VOIDED`), the system `created_at` timestamp, and the manual `transaction_date` timestamp.
* `TransactionLineItem`: Link to parent `Transaction`, relational `Product` reference, transaction item count (`quantity_sold` as Decimal), alongside immutable snapshots tracking `cost_price` and `price_at_sale` at the exact second of checkout.


* [ ] **5.3 Register Routing Decorators:** Replace global middleware with a custom `@require_open_session` view decorator applied explicitly to checkout endpoints. This eliminates N+1 database queries across static resources while properly routing locked users to the register initialization screen.

---

### 🧠 Phase 6: Service Layer Architecture (Business Logic Core)

*All code in this phase is written within isolated python functional sheets (`services.py`) across their respective apps.*

* [ ] **6.1 Atomic Checkout Processing Service (`services.process_checkout`):**
* Wrap the entire execution block within an isolated database transaction wrapper (`@transaction.atomic`).
* **Sort product IDs sequentially** before executing `.select_for_update()` to absolutely guarantee database deadlock prevention under simultaneous high-volume checkout loads.
* Iterate pricing checks, bulk-create sales records, deduct inventory totals, and update the associated client's `cached_balance` atomically.


* [ ] **6.2 Void Entry & Returns Services:**
* *Voids:* If `session == OPEN`, reverse the sale status, restore inventory tallies to the main `Product.stock_quantity`, and reverse any associated customer ledger impacts.
* *Returns:* If `session == POSTED`, block simple structural deletion or wiping. Create a distinct reversing record tracking returned items, processing refund values via cash returns or ledger credit entries.


* [ ] **6.3 General Account Ledger Processing:** Accept payment payloads directly, decrement the target customer's `cached_balance`, and write an immutable payment log.
* [ ] **6.4 Inbound Material Processing (Split Payments):** Process incoming shipments allowing for split payment payloads (`business_cash` vs. `owner_contribution`). If `owner_contribution > 0`, log the exact amount strictly to the `OwnerCapitalLedger` as a `CONTRIBUTION` to maintain a pristine corporate veil.
* [ ] **6.5 Policy-Capped Equity Draw Service:** Process owner's draws to clear store tabs automatically upon receiving inventory, constrained by the day's contribution:
```python
@transaction.atomic
def process_policy_capped_owner_draw(owner_customer_id, operator_user, contribution_amount):
    if contribution_amount <= 0: return None
    customer = Customer.objects.select_for_update().get(id=owner_customer_id)
    if not customer.is_owner or customer.cached_balance <= 0: return None

    # --- STORE POLICY LOGIC ---
    # Draw is capped at whichever is smaller: the current tab, or today's contribution.
    draw_amount = min(customer.cached_balance, contribution_amount)

    # =====================================================================
    # NOTE: If policy dictates clearing the ENTIRE tab regardless of today's
    # contribution, ensure excess amounts are split into an uncollateralized
    # equity DRAW entry for strict auditing:
    # 
    # draw_amount = customer.cached_balance
    # =====================================================================

    OwnerCapitalLedger.objects.create(
        owner_user_id=customer.user_link_id, amount=draw_amount,
        transaction_type='DRAW', reference_notes=f"Auto-applied against inventory."
    )
    Transaction.objects.create(
        session=session, cashier=operator_user, customer=customer, total_amount=-draw_amount,
        payment_type='OWNER_DRAW', payment_amount=draw_amount, status='POSTED',
        transaction_date=timezone.now()
    )

    customer.cached_balance -= draw_amount
    customer.save(update_fields=['cached_balance'])
    return draw_amount

```


* [ ] **6.6 Shift Lifecycle Termination:** Compare actual cash counts manually typed into the register layout interface by the closing staff against system math. Log variations, flip `Session.status` to `POSTED`, and lock down the financial period (transactions are already POSTED at checkout).

---

### 💻 Phase 7: Dynamic User Interface Architecture (Bootstrap Template + HTMX)

* [ ] **7.1 Master Shell Engineering:** Integrate a modern [Tailwind template](https://github.com/cruip/tailwind-dashboard-template.git) into your shared backend template workspace. Establish a clean base layout featuring a persistent navigation bar and clear alert messages. Apply role-gated visibility on the sidebar — the **System** section (User Management) is hidden from CASHIER users via `{% if request.user.is_manager %}`. All modal form containers use `bg-gray-100` for visual contrast against white input fields.
* [ ] **7.2 Product & Procurement Workspaces:** Design intuitive listing pages for inventory management. Integrate your special low-stock view, displaying low-count items grouped cleanly by vendor with HTMX triggers to compile draft Purchase Orders instantly.
* [ ] **7.3 Open-Ledger Customer CRM:** Build detailed profiles displaying general customer information alongside clear contextual panels displaying their dynamic, pre-calculated `$O(1)` cached balance statistics. Provide a quick-action overlay form to post payments instantly.
* [ ] **7.4 Real-Time HTMX Checkout Console:** Strip core sidebar elements away to establish a full-width cash register screen layout featuring a keyup-delayed search filtering input and dynamic backend-calculated HTML cart swaps.
* [ ] **7.5 Real-Time Credit Limit Shield:** Utilize `hx-include` on the payment selector to dynamically evaluate mathematical limits before allowing STORE CREDIT transactions, rendering a prominent warning alert if limits are broken:

$$\text{Projected Total} = \text{cached\_balance} + \text{Active Cart Total}$$


* [ ] **7.6 Live Audit Feed:** Create an operations log displaying historical sales across all sessions. Use HTMX to selectively render active, functional "Void" buttons for open sessions or "Process Return" actions for older locked records.
* [ ] **7.7 Inline Modal Creation & Role Gating:** Replace all standalone create-page redirects with inline modal forms (Customers, Products, Purchase Orders, Users). Gate all create/edit/delete buttons with `{% if request.user.is_manager %}` so CASHIER role only sees read-only list views. Back each modal with a dedicated `CreateView` using `ManagerOrAdminMixin`.

---

### 📈 Phase 8: Aggregations, Business Insights & Automated Reconciliation

* [ ] **8.1 High-Performance Aggregation Queries:** Write specialized data analytics models leveraging Django's `Sum` and `Count` syntax wrappers to extract total revenue, sales volume by clerk, product performance tallies, and financial splits across custom date filters.
* [ ] **8.2 Automated Cache Reconciliation Audit Task:** Build a backend maintenance command or periodic script that loops through active client accounts, calculates their balance on the fly from raw historic entries, and cross-checks it against the optimized cache value:

$$\text{cached\_balance} == \sum(\text{Transactions})$$



Any delta must drop a high-priority warning flag into an administration log to preserve financial peace of mind.
* [ ] **8.3 Management BI Dashboard:** Build an analytics view filled with summary cards highlighting critical store performance indicators, explicitly separating standard operational `CASH`/`CARD` revenue from `OWNER_DRAW` equity offsets.
* [ ] **8.4 The Shift Z-Report Interface:** Build the closing dashboard requiring employees to input physical currency counts, processing variance analysis, and executing the automated session posting lock down.

---

## 📋 Integrated POS Blueprint: Phase 9–13 Roadmap

This roadmap assumes Phases 1–8 are completed or refactored. It represents the final integrated state of the system, ordered strictly by dependency.

---

### 🔴 Phase 9: Unified Schema & Data Guardrails

*Focus: Establish the single source of truth using strict relational constraints and precise data types.*

* [ ] **9.1 Extended User Schema:** Add `pin_code` (hashed CharField) for localized cashier authentication. Update the Django Admin `UserCreateForm`.
* [ ] **9.2 Enhanced Product Schema:** Add `is_service` (Boolean) to flag 100% margin items and `is_variable_weight` (Boolean) to flag Tingi fractional items.
* [ ] **9.3 Decimal Precision Enforcement:** Update `stock_quantity` and `min_stock_level` on the `Product` model to `DecimalField` to support fractional inventory mathematically.
* [ ] **9.4 Composite Through-Table:** Implement `RecipeIngredient` linking `Product` to itself via `parent_product` and `child_product` foreign keys, enforcing a `unique_together` constraint.
* [ ] **9.5 Customer & Credit Extensions:** Add `loyalty_points` (DecimalField) and `loyalty_enabled` (Boolean) to the `Customer` model.
* [ ] **9.6 The Credit Profile:** Create the `CreditProfile` model as a `OneToOneField` to `Customer` holding `current_balance`, `credit_limit`, and `settlement_period_days`.
* [ ] **9.7 Master Transaction Schema:** Establish the `Transaction` model (replaces `Sale` entirely — data migration copies Sale records, then drops Sale/SaleItem/Payment tables) tracking `total_amount`, `status` (DRAFT/POSTED/VOIDED), the system `created_at` timestamp, and the manual `transaction_date` timestamp.
* [ ] **9.8 Line Item Normalization:** Create `TransactionLineItem` linked to `Transaction` and `Product`, capturing immutable snapshots of `quantity_sold`, `price_at_sale`, and `cost_price`.
* [ ] **9.9 The Session-Locked Cashbook:** Build the `Ledger` model requiring strict foreign keys to both the current `Session` and the triggering `Transaction`. Ensure all financial foreign keys utilize `on_delete=models.RESTRICT` to guarantee immutability.

---

### 🟠 Phase 10: Service Layer & Business Logic

*Focus: Encapsulate all complex operations inside pure Python functions to protect the database and future-proof the UI.*

* [x] **10.1 Composite Inventory Deduction:** Write `services.deduct_composite(product, quantity)`. Use `F()` expressions to deduct child ingredients if a `RecipeIngredient` relation exists, otherwise deduct the parent directly. Wrap in a `.select_for_update()` lock. Located in `inventory/services.py`.
* [x] **10.2 Atomic Ledger Coupling:** Write `services.write_ledger_entry(session, transaction, amount, type)`. This must execute within the same `transaction.atomic()` block as the checkout to prevent orphaned financial states. Located in `accounting/services.py`.
* [x] **10.3 Loyalty Math Guardrails:** Write `services.award_loyalty_points(customer, total)`. Implement `math.floor(total / 10)` to award exactly **1 point per $10 spent** on non-credit sales, preventing decimal point bloat. Located in `customers/services.py`.
* [x] **10.4 The Equity Offset Routine:** Write `services.equity_offset(admin, customer, amount)`. This function must clear the target's `CreditProfile` balance, log an `OwnerCapitalLedger` contribution, and write a correction to the `Ledger`. Located in `accounting/services.py`.
* [x] **10.5 Virtual Session Offline Recovery:** Write `services.batch_offline_recovery(rows)`. This function must auto-generate a closed "Virtual Session" to protect the active drawer. It maps user-provided dates to `transaction_date`, but deducts inventory *real-time* via `services.deduct_composite()`. Located in `sales/services.py`.

---

### 🟡 Phase 11: The Zero-Lag Cart Engine (Alpine.js)

*Focus: Eliminate database I/O churn by managing the active checkout state entirely within the client's browser memory.*

* [ ] **11.1 Client-Side Store Initialization:** Define an Alpine.js `posCart()` component in your base template. Establish an empty array to track scanned items and a computed property to calculate the running total mathematically.
* [ ] **11.2 Cart Mutation Micro-Interactions:** Write the Alpine.js methods `addItem()`, `updateQuantity()`, and `removeItem()`. Bind these directly to the `+`, `-`, and `Trash` UI buttons.
* [ ] **11.3 The Tingi Interceptor:** Within `addItem()`, evaluate the `is_variable_weight` flag. If true, instantly halt the standard scan flow and trigger a client-side Alpine prompt to capture the fractional decimal quantity from the cashier.
* [ ] **11.4 Payload Assembly & Handoff:** Write a `submitCheckout()` method in Alpine.js that serializes the final cart array into JSON and dispatches a custom window event.
* [ ] **11.5 HTMX Submission Trigger:** Create a hidden HTML form that listens for the custom Alpine event, injects the JSON payload into an input field, and triggers an HTMX POST request to the Django backend for final, single-step atomic processing.

---

### 🟢 Phase 12: UI/UX & Analytical Dashboards

*Focus: Build out the reactive layouts and business intelligence reporting.*

* [ ] **12.1 Hardware-Aware Base Layouts:** Integrate the Tailwind CSS templates. Build the mobile single-column layout with the persistent bottom nav, and the desktop two-column layout snapping the cart to the left.
* [ ] **12.2 Security Stripping:** Apply Django template logic (`{% if request.user.is_manager %}`) to physically strip restricted elements from the DOM before HTMX delivers the HTML payload to the client.
* [ ] **12.3 Quick Service Grid Integration:** Build the layout for 100% margin services, wiring the buttons to instantly call the Alpine.js `addItem()` method without backend routing.
* [ ] **12.4 The Tendered Cash Modal:** Construct an Alpine.js modal featuring a custom numeric keypad. Implement "Quick Cash" shortcut buttons and client-side change calculations to bypass the native mobile OS keyboard.
* [ ] **12.5 Realization-Based Analytics:** Build the Admin Dashboard. Write Django ORM aggregation queries for Daily Sales that explicitly group by the `transaction_date` field instead of `created_at` to reflect actual business reality. Add the "Cloud Backup Sync Status" infrastructure widget.
* [ ] **12.6 Offline Spreadsheet Interface:** Build the dense data-entry grid. Implement Alpine.js keyboard navigation (Tab/Arrows) and non-blocking inline cell validation.

---

### 🔵 Phase 13: Hardware Orchestration & DevOps

*Focus: Protect local system time, manage asynchronous hardware tasks, and secure deployment.*

* [ ] **13.1 The NTP Time Guardrail:** Update your `docker/entrypoint.sh` script to ping a local router or known reliable IP to verify the system time. If the date is grossly inaccurate (indicating a dead CMOS battery), force the script to exit with an error before Django boots.
* [ ] **13.2 Asynchronous Printer Handoff:** Configure `django-q2` using PostgreSQL as the broker. Move the raw TCP/IP socket printing logic into an asynchronous background task to prevent the HTMX web request from hanging.
* [ ] **13.3 Rapid Data Seeding:** Build a custom Django management command leveraging `bulk_create()` to ingest a CSV template and rapidly populate `Product` and `RecipeIngredient` tables for Day-1 launch.
* [ ] **13.4 Automated Snapshot Backups:** Write a Django management command that dumps the PostgreSQL database, compresses it, pushes it to an S3 bucket, and updates a tracking timestamp. Schedule this daily via Django-Q.
* [ ] **13.5 Container Registry Pipeline:** Finalize the `deploy.sh` script on the host machine to execute `docker compose pull && docker-compose up -d && docker system prune` to pull compiled images directly over the WAN.

---

### 🗺️ Final Dependency Flow Graph

```text
Phase 9 (Models) ───── Phase 10 (Services) ───── Phase 11 (Cart State) ── Phase 12 (UI & Dashboards)
  9.1 User                  │                              │                      │
  9.2 Product               │                              │                      │
  9.4 Recipe ────────────── 10.1 Composite Deduct          │                      │
  9.5 CreditProfile ─────── 10.3 Loyalty, 10.4 Equity      11.1 Alpine Init ───── 12.1 Base Layout
  9.7 Transaction ───────── 10.5 Offline Virtual Sessions  11.2 Micro-Interacts ─ 12.3 Quick Service
  9.9 Session Ledger ────── 10.2 Atomic Ledger Coupling    11.3 Tingi Prompt ──── 12.4 Cash Modal
                                                            11.4 Handoff           12.5 BI Dashboard (Date Aggregation)
                                                                                   12.6 Offline Grid

                                                                            Phase 13 (DevOps)
                                                                              13.1 NTP Check
                                                                              13.2 Async Print
                                                                              13.4 Cloud Backup
```

---

### Design Decisions (Confirmed)

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Sale→Transaction migration | **Direct replacement** — data migration copies Sales, then drops Sale/SaleItem/Payment tables | Cleaner schema, no dual-write complexity |
| 2 | Alpine.js cart crash risk | **Accepted** — LAN-based POS has stable devices; browser crash mid-cart is rare | Performance gain outweighs edge-case risk |
| 3 | Ledger FK to Session (non-nullable) | **Accepted** — Equity Offset and Offline Recovery auto-create sessions | Ensures zero orphaned ledger entries |
| 4 | Loyalty award rate | **1pt per $10** (`math.floor(total / 10)`) | Prevents inflation in low-margin retail |
| 5 | Virtual Session for offline recovery | **Accepted** — auto-generates POSTED virtual session | Protects active drawer integrity |
| 6 | Execution order | **Phase 9 → 10 → 11+12 → 13** | Strict dependency ordering |

---

### File Change Summary

| File | Action | Phase |
|------|--------|-------|
| `users/models.py` | +`pin_code` field | 9.1 |
| `users/forms.py` | +`pin_code` in form | 9.1 |
| `inventory/models.py` | +`is_service`, `is_variable_weight`, `RecipeIngredient`, M2M field, Decimal stock fields | 9.2–9.4 |
| `customers/models.py` | +`loyalty_points`, `loyalty_enabled`; NEW `CreditProfile` | 9.5–9.6 |
| `sales/models.py` | NEW `Transaction`, `TransactionLineItem`; DROP `Sale`, `SaleItem`, `Payment` | 9.7–9.8 |
| `accounting/models.py` | NEW `Ledger` | 9.9 |
| `sales/admin.py` | Replace Sale→Transaction inline configs | 9.7 |
| `customers/admin.py` | +CreditProfile inline | 9.6 |
| `accounting/admin.py` | +LedgerAdmin | 9.9 |
| All model files | `on_delete=models.RESTRICT` on financial FKs | 9.9 |
| `inventory/services.py` | NEW `deduct_composite`, `restore_composite` | 10.1 |
| `accounting/services.py` | NEW `write_ledger_entry`, `equity_offset` | 10.2, 10.4 |
| `customers/services.py` | NEW `award_loyalty_points` | 10.3 |
| `sales/services.py` | REFACTOR `process_checkout` (deduct_composite, write_ledger_entry, award_loyalty_points); NEW `batch_offline_recovery`; REFACTOR `void_sale`→`void_transaction` | 10.2–10.5 |
| `inventory/views.py` | NEW `VendorListView`, `VendorCreateView` | 4.1 |
| `inventory/urls.py` | +`vendors/`, `vendors/create/` routes | 4.1 |
| `templates/inventory/vendor_list.html` | NEW: paginated table + New Vendor modal | 4.1 |
| `customers/views.py` | NEW `CustomerUpdateView` | 3.5 |
| `customers/urls.py` | +`<int:pk>/edit/` route | 3.5 |
| `templates/customers/customer_form.html` | NEW: full-page edit form | 3.5 |
| `templates/customers/customer_list.html` | +Edit button per row (manager-gated); expanded modal fields (credit_limit, allow_pay_later, is_owner, loyalty_enabled); cashiers see `$---` for owner credit limits | 3.5 |
| `templates/base.html` | +Alpine.js CDN, `posCart()` script, dark mode store, mobile bottom nav | 11.1, 12.1 |
| `templates/sales/checkout.html` | FIX: added `name="q"` to search input, restructured cart panel container | 7.4 |
| `templates/sales/partials/cart_summary.html` | REWRITE: consolidated cart items + payment form into single `#cart-panel` with HTMX swap; payment form now appears after first item added; all HTMX targets updated to `#cart-panel` | 7.4 |
| `templates/sales/partials/product_results.html` | FIX: changed `hx-target` from `#cart-summary` → `#cart-panel` | 7.4 |
| `sales/views.py` | FIX: CartAddView, CartRemoveView, CartUpdateQtyView now pass `customers` context for payment form dropdown | 7.4 |
| `templates/sales/partials/quick_service_grid.html` | NEW | 12.3 |
| `templates/sales/partials/cash_modal.html` | NEW | 12.4 |
| `templates/sales/dashboard.html` | REFRESH: transaction_date aggregation, backup widget | 12.5 |
| `templates/sales/offline_recovery.html` | NEW | 12.6 |
| All templates | RBAC wrapping on restricted elements | 12.2 |
| `sales/views.py` | REWRITE CheckoutView (Alpine data), REFACTOR DashboardView (transaction_date), NEW OfflineRecoveryView | 11.5, 12.5–12.6 |
| `sales/urls.py` | +`offline-recovery/` route | 12.6 |
| `sales/analytics.py` | UPDATE queries to use `transaction_date` | 12.5 |
| `docker/entrypoint.sh` | NEW: NTP check, migrate, admin bootstrap | 13.1 |
| `docker/Dockerfile` | ADD entrypoint.sh | 13.1 |
| `docker-compose.yml` | +Django-Q service, +backup env vars | 13.2, 13.4 |
| `core/management/commands/seed_products.py` | NEW | 13.3 |
| `core/management/commands/cloud_backup.py` | NEW | 13.4 |
| `pyproject.toml` | +`django-q2`, +`boto3` | 13.2, 13.4 |
| `deploy.sh`, `DEPLOY.md` | NEW | 13.5 |
