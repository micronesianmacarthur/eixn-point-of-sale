# 📋 Integrated POS Blueprint: Phase 9–13 Roadmap

This roadmap assumes Phases 1–8 are completed or refactored. It represents the final integrated state of the system, ordered strictly by dependency.

---

## 🔴 Phase 9: Unified Schema & Data Guardrails

*Focus: Establish the single source of truth using strict relational constraints and precise data types.*

* **9.1 Extended User Schema:** Add `pin_code` (hashed CharField) for localized cashier authentication. Update the Django Admin `UserCreateForm`.
* **9.2 Enhanced Product Schema:** Add `is_service` (Boolean) to flag 100% margin items and `is_variable_weight` (Boolean) to flag Tingi fractional items.
* **9.3 Decimal Precision Enforcement:** Update `stock_quantity` and `min_stock_level` on the `Product` model to `DecimalField` to support fractional inventory mathematically.
* **9.4 Composite Through-Table:** Implement `RecipeIngredient` linking `Product` to itself via `parent_product` and `child_product` foreign keys, enforcing a `unique_together` constraint.
* **9.5 Customer & Credit Extensions:** Add `loyalty_points` (DecimalField) and `loyalty_enabled` (Boolean) to the `Customer` model.
* **9.6 The Credit Profile:** Create the `CreditProfile` model as a `OneToOneField` to `Customer` holding `current_balance`, `credit_limit`, and `settlement_period_days`.
* **9.7 Master Transaction Schema:** Establish the `Transaction` model (bypassing the concept of `Sale`) tracking `total_amount`, `status` (DRAFT/POSTED/VOIDED), the system `created_at` timestamp, and the manual `transaction_date` timestamp.
* **9.8 Line Item Normalization:** Create `TransactionLineItem` linked to `Transaction` and `Product`, capturing immutable snapshots of `quantity_sold`, `price_at_sale`, and `cost_price`.
* **9.9 The Session-Locked Cashbook:** Build the `Ledger` model requiring strict foreign keys to both the current `Session` and the triggering `Transaction`. Ensure all financial foreign keys utilize `on_delete=models.RESTRICT` to guarantee immutability.

---

## 🟠 Phase 10: Service Layer & Business Logic

*Focus: Encapsulate all complex operations inside pure Python functions to protect the database and future-proof the UI.*

* **10.1 Composite Inventory Deduction:** Write `services.deduct_composite(product, quantity)`. Use `F()` expressions to deduct child ingredients if a `RecipeIngredient` relation exists, otherwise deduct the parent directly. Wrap in a `.select_for_update()` lock.
* **10.2 Atomic Ledger Coupling:** Write `services.write_ledger_entry(session, transaction, amount, type)`. This must execute within the same `transaction.atomic()` block as the checkout to prevent orphaned financial states.
* **10.3 Loyalty Math Guardrails:** Write `services.award_loyalty_points(customer, total)`. Implement a strict `math.floor(total)` calculation to award exactly 1 point per whole ten dollar spent on non-credit sales, preventing decimal point bloat.
* **10.4 The Equity Offset Routine:** Write `services.equity_offset(admin, customer, amount)`. This function must clear the target's `CreditProfile` balance, log an `OwnerCapitalLedger` contribution, and write a correction to the `Ledger`.
* **10.5 Virtual Session Offline Recovery:** Write `services.batch_offline_recovery(rows)`. This function must auto-generate a closed "Virtual Session" to protect the active drawer. It maps user-provided dates to `transaction_date`, but deducts inventory *real-time* via `services.deduct_composite()`.

---

## 🟡 Phase 11: The Zero-Lag Cart Engine (Alpine.js)

*Focus: Eliminate database I/O churn by managing the active checkout state entirely within the client's browser memory.*

* **11.1 Client-Side Store Initialization:** Define an Alpine.js `posCart()` component in your base template. Establish an empty array to track scanned items and a computed property to calculate the running total mathematically.
* **11.2 Cart Mutation Micro-Interactions:** Write the Alpine.js methods `addItem()`, `updateQuantity()`, and `removeItem()`. Bind these directly to the `+`, `-`, and `Trash` UI buttons.
* **11.3 The Tingi Interceptor:** Within `addItem()`, evaluate the `is_variable_weight` flag. If true, instantly halt the standard scan flow and trigger a client-side Alpine prompt to capture the fractional decimal quantity from the cashier.
* **11.4 Payload Assembly & Handoff:** Write a `submitCheckout()` method in Alpine.js that serializes the final cart array into JSON and dispatches a custom window event.
* **11.5 HTMX Submission Trigger:** Create a hidden HTML form that listens for the custom Alpine event, injects the JSON payload into an input field, and triggers an HTMX POST request to the Django backend for final, single-step atomic processing.

---

## 🟢 Phase 12: UI/UX & Analytical Dashboards

*Focus: Build out the reactive layouts and business intelligence reporting.*

* **12.1 Hardware-Aware Base Layouts:** Integrate the Tailwind CSS templates. Build the mobile single-column layout with the persistent bottom nav, and the desktop two-column layout snapping the cart to the left.
* **12.2 Security Stripping:** Apply Django template logic (`{% if request.user.is_manager %}`) to physically strip restricted elements from the DOM before HTMX delivers the HTML payload to the client.
* **12.3 Quick Service Grid Integration:** Build the layout for 100% margin services, wiring the buttons to instantly call the Alpine.js `addItem()` method without backend routing.
* **12.4 The Tendered Cash Modal:** Construct an Alpine.js modal featuring a custom numeric keypad. Implement "Quick Cash" shortcut buttons and client-side change calculations to bypass the native mobile OS keyboard.
* **12.5 Realization-Based Analytics:** Build the Admin Dashboard. Write Django ORM aggregation queries for Daily Sales that explicitly group by the `transaction_date` field instead of `created_at` to reflect actual business reality. Add the "Cloud Backup Sync Status" infrastructure widget.
* **12.6 Offline Spreadsheet Interface:** Build the dense data-entry grid. Implement Alpine.js keyboard navigation (Tab/Arrows) and non-blocking inline cell validation.

---

## 🔵 Phase 13: Hardware Orchestration & DevOps

*Focus: Protect local system time, manage asynchronous hardware tasks, and secure deployment.*

* **13.1 The NTP Time Guardrail:** Update your `docker/entrypoint.sh` script to ping a local router or known reliable IP to verify the system time. If the date is grossly inaccurate (indicating a dead CMOS battery), force the script to exit with an error before Django boots.
* **13.2 Asynchronous Printer Handoff:** Configure `django-q2` using PostgreSQL as the broker. Move the raw TCP/IP socket printing logic into an asynchronous background task to prevent the HTMX web request from hanging.
* **13.3 Rapid Data Seeding:** Build a custom Django management command leveraging `bulk_create()` to ingest a CSV template and rapidly populate `Product` and `RecipeIngredient` tables for Day-1 launch.
* **13.4 Automated Snapshot Backups:** Write a Django management command that dumps the PostgreSQL database, compresses it, pushes it to an S3 bucket, and updates a tracking timestamp. Schedule this daily via Django-Q.
* **13.5 Container Registry Pipeline:** Finalize the `deploy.sh` script on the host machine to execute `docker compose pull && docker-compose up -d && docker system prune` to pull compiled images directly over the WAN.

---

## 🗺️ Final Dependency Flow Graph

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
