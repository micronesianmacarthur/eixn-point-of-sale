---
name: verify-print
description: Verify a receipt/print template change end-to-end in this repo. Use when editing sales/receipt.html or other printable templates, when asked to check a print layout, page breaks, or column alignment. Not for WeasyPrint-based checks (WeasyPrint renders this project unstyled — see body).
---

# Verify printed output

WeasyPrint ignores Tailwind v4 `@layer` rules, so it renders this project's receipts
unstyled. Always verify print with headless Chromium.

## 1. Render the template

Render through the Django test client inside a rolled-back transaction (no DB writes):

1. Write a throwaway script under `/tmp/opencode` (never in the repo) that, roughly:
   - points at the scratch DB: `DATABASE_URL=postgres://eixn:eixn@172.20.0.2:5432/eixn_pos`
   - creates `BusinessInfo` (SetupCheckMiddleware 302-redirects authenticated users without it)
   - seeds a demo user + `Customer` + `Transaction` + `TransactionLineItem`(s) + `Payment`(s)
     inside `with transaction.atomic(), transaction.set_rollback(True):`
   - GETs the receipt via `django.test.Client()` with `HTTP_HOST='localhost'` (testserver
     trips `DisallowedHost`)
   - writes `response.content` to `backend/.tmp_receipt.html`
2. Seeding inside `set_rollback(True)` means nothing persists; you only need the rendered HTML.

## 2. Serve and print

- Serve `backend/` (so `/static/css/app.css` resolves) from the `backend/` directory:
  `python3 -m http.server 8867`
- Print: `/usr/bin/chromium --headless=new --no-sandbox --no-pdf-header-footer --print-to-pdf=out.pdf http://localhost:8867/.tmp_receipt.html`
- Inspect with `pdftotext -bbox out.pdf`:
  - label right edges (e.g. `Ticket No:`, `PO Number:`, `Sub Total`) should share one x
  - value columns should land on their expected x (right-aligned block ~col 7)
  - confirm the expected page count (`pdfinfo out.pdf | rg '^Pages'`) and no print chrome

## 3. Cleanup — never use pkill

`pkill -f <pattern>` matches the calling shell's own command line and kills the session.
Stop the server with:
`pgrep -ax python3 | awk '/http.server 8867/{print $1}'` then `kill <pid>`.
Remove `backend/.tmp_receipt.html` afterwards.

## Ports

8091 is occupied by another service (Prowlarr); demo print servers have used 8867.