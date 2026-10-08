---
name: add-payment-type
description: Add or rename a Payment.PaymentType option end-to-end in this POS — model choices, checkout buttons, labels, receipt legs, tests. Use when adding a new payment method or relabeling one (e.g. the "Account"/store-credit label).
---

# Adding a PaymentType option

1. **Model** — add the choice to `Payment.PaymentType` in `sales/models.py`. The label is the
   POS display term (e.g. `ACCOUNT = 'ACCOUNT', 'Account'`). A value change rewrites existing
   rows, so it needs a `RunPython` data migration (see the `migrate-data` skill); a label-only
   change also produces a migration: run `manage.py makemigrations --check --dry-run`; apply with
   `migrate` on the **scratch** DB only (`DATABASE_URL=postgres://eixn:eixn@172.20.0.2:5432/eixn_pos`),
   never against the dev DB (localhost:5433).

2. **Checkout buttons (Alpine path)** — `backend/templates/sales/checkout.html`:
   - add a "Pay With" tender button that calls `addLeg('<TYPE>')`
   - add an `<option>` to the refund-method `<select>` (returns) if applicable

3. **paymentLabel() JS** — `backend/templates/base.html` maps types to display names used by the
   Alpine cart (`paymentLabel(leg.type)`); add the new type there.

4. **HTMX cart path** — `backend/templates/sales/partials/cart_summary.html` payment_type
   select options (single-tender checkout).

5. **Receipt legs need no change** — `ReceiptView` builds `payment_legs` from
   `Payment.PaymentType(payment_type).label`: the label flows into the full-page legs, and the
   72 mm block + customer detail via `get_payment_type_display()`.

6. **Tests** — in `sales/tests.py` assert:
   - legs render only the types used in the sale (unused types absent)
   - the display label, e.g. `['Account']` and `assertNotContains('Store Credit')`

7. **Terminology** — the POS display term for the `ACCOUNT` payment type (store credit) is
   "Account", and the stored DB value is `'ACCOUNT'`.

8. Log the change in `docs/progress.md`.