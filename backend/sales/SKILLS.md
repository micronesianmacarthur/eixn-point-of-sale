# sales — domain map

Reference for the sales app (checkout → payment → receipt → close). A lander, not a runbook:
machine-loadable procedures live in the repo's opencode skills (`verify-print`,
`add-payment-type`, `run-tests`, `migrate-data` in `.opencode/skills/`).

## Flow

PosCart (Alpine, `posCart()` in `base.html`) → `checkout.html` → `CheckoutCompleteView`
(`checkout_complete`) → `process_checkout` in `services.py` → `ReceiptView` (`receipt.html`).
Thermal/text receipt printed async: `async_task('core.tasks.print_receipt', txn.id)` →
`build_receipt_lines` in `receipts.py`. Sessions: `SessionCreateView` opens, `close_session`
(`services.py:294`) → `SessionCloseView` + Z-report (`ZReportPDFView`, `analytics.get_session_pnl`).

## Locations

- **Models** — `models.py`: `Session`, `Transaction`, `TransactionLineItem`, `Payment`
  (`PaymentType`: CASH/Card/STORE_CREDIT=**Account**/OWNER_DRAW). Money is `Decimal` everywhere.
- **Business logic** — `services.py`: `process_checkout`, `void_transaction`, `process_return`,
  `close_session`, `process_customer_payment`, `receive_inventory`, `batch_offline_recovery`,
  `normalize_payments`, `to_cents`.
- **Analytics** — `analytics.py`: `get_daily_sales_stats`, `get_sales_by_clerk`, `get_top_products`,
  `get_payment_type_breakdown`, `get_daily_trend`, `get_session_pnl`, `get_customer_debt_ranking`,
  `get_weekly_comparison`.
- **Cash counting** — `cash_count.py`.
- **Receipt text** — `receipts.py`: `build_receipt_lines` (thermal printer text).
- **Views** — `views.py`: `CheckoutView`/`CheckoutCompleteView`/`ReceiptView`/
  `TransactionDetailView`/`VoidSaleView`/`ReturnSaleView`/`OfflineRecoveryView`/
  `SessionCreateView`/`SessionCloseView`/`StepCountView`/`StepRemoveView`/`StepReviewView`/
  `ZReportPDFView`/`SaleListView`/`SaleListTableView`/`TopProductsView`/`CreditCheckView`.
  `ReceiptView.get_context_data` exports `payment_legs` (one leg per payment type actually used,
  labeled via `Payment.PaymentType(type).label`) and `payment_total`.
- **Templates** — `backend/templates/sales/`: `checkout.html` (Alpine cart/tenders),
  `partials/cart_summary.html` (HTMX single-tender path), `receipt.html` (full-page #receipt-full +
  #receipt-small 72 mm), `sale_list.html`, `transaction_detail.html`, `session_close.html`,
  `offline_recovery.html`, `close/` (step flow + `zreport_content.html`).

## Invariants

- The POS display term for `STORE_CREDIT` is **"Account"** everywhere (model label, checkout
  `paymentLabel()`, receipt legs). `"Store Credit"` in `session_close.html` / `offline_recovery.html`
  / `zreport_content.html` are stale leftovers.
- Receipt legs show only the tender types used in the sale.
- No-floats money: quantize to 0.01 with `ROUND_HALF_UP`.
- Print verification uses headless Chromium, never WeasyPrint (drops Tailwind v4 `@layer` rules).
- Never block a request for printing — always go through `core.tasks`.

## Recurring tasks

- Editing receipts/print layout → run the **verify-print** skill.
- Adding/renaming a payment type → run the **add-payment-type** skill.
- Running/interpreting tests → **run-tests** skill; data migrations → **migrate-data** skill.
- Log every change in `docs/progress.md` under the dated heading.