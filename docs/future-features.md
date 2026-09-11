# Future Features

Features deferred to future versions of eixn-pos.

## Online Backup (Cloud Backup Sync)
> **Status updated 2026-09-11:** no longer deferred — scheduled daily backups and the dashboard widget are now implemented (see `docs/progress.md`).

## Loan Management Module

- **Status:** Planned
- **Planned for:** Future release
- **Reference:** `loan-feature-plan.md` (full implementation plan)
- **Description:** Dedicated loan management module for disbursing and tracking customer loans with daily interest accrual. Includes loan checkout, repayment processing, outstanding balance tracking, and customer search integration.
- **Key components (from plan):**
  - `loans` Django app with `Loan` model (statuses: ACTIVE, PAID, WRITTEN_OFF)
  - Service layer: `disburse_loan()`, `process_repayment()`, `annotate_outstanding()`
  - Views: `LoanListView`, `LoanCreateView`, `LoanDetailView`, `LoanRepayView`, `LoanCustomerSearchView`
  - Templates: create form with HTMX customer search, list with status filter tabs, detail with inline repayment form
  - Integration: nav link in `base.html`, optional loans section on customer detail page
  - Configurable interest rate via `SystemSetting` (`LOAN_INTEREST_RATE`)
- **Edge cases covered:** concurrent repayment locking, negative outstanding clamping, PROTECT on customer FK, manager override for large amounts, written-off reversal
- **Estimated effort:** 2–3 days (16 new files, 3 modified)
- **Date noted:** 2026-09-10

---

## Settings Page — Move Page-Level Buttons to Top

- **Status:** Planned
- **Planned for:** Future release
- **Description:** Move the `Admin Panel` and `Save Settings` buttons in the system settings page (`templates/core/settings.html`) from below the tab content to the top of the page.
- **Implementation notes:** Currently these buttons render at the bottom of the form (outside the tab panels). They should sit above the tabbed section so they remain visible regardless of which tab is active.
- **Date noted:** 2026-09-10
