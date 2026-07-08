# Close Session — 3-Step Implementation Plan

## Overview

Replace the single-field `ending_cash_actual` modal with a **dedicated 3-step page**:
1. **Count** — per-denomination cash counting grid with live totals
2. **Remove** — greedy algorithm suggests exact coins/bills to extract, mandatory confirmation
3. **Z-Report** — print-ready summary + final "Post & Close" button

---

## Step 0: New Service — `sales/cash_count.py`

Pure functions, no framework dependency. Port of `temp/cash_logic.py`.

```python
from decimal import Decimal

CURRENCY_DEFS = [
    (Decimal('0.01'), 'pennies', 'coins'),
    (Decimal('0.05'), 'nickels', 'coins'),
    (Decimal('0.10'), 'dimes', 'coins'),
    (Decimal('0.25'), 'quarters', 'coins'),
    (Decimal('0.50'), 'half_dollars', 'coins'),
    (Decimal('1.00'), 'dollars', 'coins'),
    (Decimal('2.00'), 'two_dollars', 'coins'),
    (Decimal('5.00'), 'fives', 'bills'),
    (Decimal('10.00'), 'tens', 'bills'),
    (Decimal('20.00'), 'twenties', 'bills'),
    (Decimal('50.00'), 'fifties', 'bills'),
    (Decimal('100.00'), 'hundreds', 'bills'),
]

def calculate_totals(counts: dict[str, int]) -> dict:
    """
    counts = {'pennies': 4, 'nickels': 2, ..., 'hundreds': 1}
    Returns:
      {'bills': Decimal('186.00'),
       'coins': Decimal('0.64'),
       'grand_total': Decimal('186.64'),
       'breakdown': [{'key': 'pennies', 'count': 4, 'amount': Decimal('0.04'), 'category': 'coins'}, ...]}
    """
    totals = {'bills': Decimal('0'), 'coins': Decimal('0')}
    breakdown = []
    for val, key, cat in CURRENCY_DEFS:
        count = counts.get(key, 0)
        amount = count * val
        totals[cat] += amount
        breakdown.append({'key': key, 'count': count, 'amount': amount, 'category': cat})
    totals['grand_total'] = totals['bills'] + totals['coins']
    totals['breakdown'] = breakdown
    return totals

def calculate_removal(remove_amount: Decimal, available_counts: dict[str, int]) -> dict:
    """
    Greedy algorithm — largest denominations first.
    Returns:
      {'counts': {'hundreds': 0, 'fifties': 1, ...},
       'amounts': {'hundreds': Decimal('0'), 'fifties': Decimal('50'), ...},
       'category_totals': {'bills': Decimal('...'), 'coins': Decimal('...')},
       'total_removed': Decimal('...'),
       'remaining': Decimal('...')}  # > 0 if cannot make exact change
    """
    results = {
        'counts': {},
        'amounts': {},
        'category_totals': {'bills': Decimal('0'), 'coins': Decimal('0')},
        'total_removed': Decimal('0'),
        'remaining': remove_amount,
    }
    remaining = remove_amount
    # Process bills first (largest), then coins (largest)
    sorted_defs = sorted(CURRENCY_DEFS, key=lambda x: x[0], reverse=True)
    for val, key, cat in sorted_defs:
        available = available_counts.get(key, 0)
        count_taken = min(int(remaining / val), available)
        amount_taken = count_taken * val
        remaining -= amount_taken
        results['total_removed'] += amount_taken
        results['category_totals'][cat] += amount_taken
        results['counts'][key] = count_taken
        results['amounts'][key] = amount_taken
    results['remaining'] = remaining
    return results
```

**Files:** `backend/sales/cash_count.py` (new)

---

## Step 1: Session Model — Add Cash Count Breakdown

**Decision: Use JSONField.**

```python
# sales/models.py — Session model
cash_count_breakdown = models.JSONField(null=True, blank=True,
    help_text='Per-denomination counts entered at session close')
```

Stores e.g. `{"pennies": 4, "nickels": 2, ..., "hundreds": 1}`.

**Why:** Full audit trail — counts are replayable if variance is disputed, and can be rendered on historical Z-reports. The storage cost is negligible (one JSON blob per session).

---

## Step 2: Rebuild `SessionCloseView` as Multi-Step

Replace `UpdateView` with a custom view that tracks step via URL or session:

```
GET  /sales/sessions/<pk>/close/         → Step 1 (Count)
POST /sales/sessions/<pk>/close/count/   → validate counts, redirect to Step 2
GET  /sales/sessions/<pk>/close/remove/  → Step 2 (Remove)
POST /sales/sessions/<pk>/close/remove/  → confirm removal, redirect to Step 3
GET  /sales/sessions/<pk>/close/review/  → Step 3 (Z-Report + Post)
POST /sales/sessions/<pk>/close/post/    → finalize, call close_session(), redirect to dashboard
```

### View pseudo-code

```python
from decimal import Decimal
from django.views.generic import View
from .cash_count import CURRENCY_DEFS, calculate_totals, calculate_removal
from .services import close_session


SESSION_COUNT_KEY = 'session_cash_counts'


class StepCountView(LoginRequiredMixin, DetailView):
    """Step 1: Cash counting grid."""
    model = Session
    template_name = 'sales/close/step1_count.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['currency_defs'] = CURRENCY_DEFS
        # Restore previously entered counts (if returning after validation error)
        saved = self.request.session.get(SESSION_COUNT_KEY, {})
        context['saved_counts'] = saved.get(str(self.object.pk), {})
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        counts = {}
        for _, key, _ in CURRENCY_DEFS:
            raw = request.POST.get(f'count_{key}', '0')
            try:
                counts[key] = max(0, int(raw))
            except (ValueError, TypeError):
                counts[key] = 0

        totals = calculate_totals(counts)

        # Validate: drawer total must be >= starting_cash
        if totals['grand_total'] < session.starting_cash:
            messages.error(request, 'Drawer total cannot be less than starting cash.')
            request.session[SESSION_COUNT_KEY] = {str(session.pk): counts}
            return redirect('sales:close_step1', pk=session.pk)

        # Store counts in session for next step
        if SESSION_COUNT_KEY not in request.session:
            request.session[SESSION_COUNT_KEY] = {}
        request.session[SESSION_COUNT_KEY][str(session.pk)] = counts
        request.session.modified = True

        return redirect('sales:close_step2', pk=session.pk)


class StepRemoveView(LoginRequiredMixin, DetailView):
    """Step 2: Cash removal calculation + confirmation."""
    model = Session
    template_name = 'sales/close/step2_remove.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = self.request.session.get(SESSION_COUNT_KEY, {}).get(str(self.object.pk))
        if not counts:
            return redirect('sales:close_step1', pk=self.object.pk)

        totals = calculate_totals(counts)
        remove_amount = totals['grand_total'] - self.object.starting_cash
        removal = calculate_removal(remove_amount, counts) if remove_amount > 0 else None

        context.update({
            'currency_defs': CURRENCY_DEFS,
            'counts': counts,
            'totals': totals,
            'remove_amount': remove_amount,
            'removal': removal,
            'starting_cash': self.object.starting_cash,
        })
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        counts = request.session.get(SESSION_COUNT_KEY, {}).get(str(session.pk))
        if not counts:
            messages.error(request, 'Session expired. Please re-enter counts.')
            return redirect('sales:close_step1', pk=session.pk)

        action = request.POST.get('action')
        if action == 'back':
            return redirect('sales:close_step1', pk=session.pk)
        if action == 'confirm':
            # Store final totals for the review page
            totals = calculate_totals(counts)
            request.session['session_close_final'] = {
                'counts': counts,
                'grand_total': str(totals['grand_total']),
            }
            request.session.modified = True
            return redirect('sales:close_step3', pk=session.pk)
        return redirect('sales:close_step2', pk=session.pk)


class StepReviewView(LoginRequiredMixin, DetailView):
    """Step 3: Z-Report + Post button."""
    model = Session
    template_name = 'sales/close/step3_review.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pnl = get_session_pnl(self.object.pk)
        context['pnl'] = pnl
        context['expected_cash'] = self.object.starting_cash + pnl['total_revenue']

        final = self.request.session.get('session_close_final', {})
        if final:
            context['grand_total'] = Decimal(final['grand_total'])
            context['counts'] = final['counts']
            context['currency_defs'] = CURRENCY_DEFS
        else:
            # Should not happen — redirect back if no data
            pass
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        final = request.session.get('session_close_final')
        if not final:
            messages.error(request, 'Session data expired. Please start over.')
            return redirect('sales:close_step1', pk=session.pk)

        actual_cash = Decimal(final['grand_total'])

        result = close_session(
            session_id=session.pk,
            actual_cash=actual_cash,
            closed_by_user=request.user,
        )

        # Store denomination breakdown for audit trail
        session.cash_count_breakdown = final['counts']
        session.save(update_fields=['cash_count_breakdown'])

        # Cleanup session keys
        self._cleanup(request, session.pk)

        if result['variance'] != 0:
            messages.warning(request, f'Session closed with variance: ...')
        messages.success(request, 'Session closed and posted.')
        return redirect('sales:dashboard')

    def _cleanup(self, request, session_pk):
        if SESSION_COUNT_KEY in request.session:
            request.session[SESSION_COUNT_KEY].pop(str(session_pk), None)
        if 'session_close_final' in request.session:
            del request.session['session_close_final']
        request.session.modified = True
```

**Files:**
- `backend/sales/views.py` — add `StepCountView`, `StepRemoveView`, `StepReviewView`
- `backend/sales/urls.py` — add 5 new routes

---

## Step 3: URLs

```python
# sales/urls.py — add:
path('sessions/<int:pk>/close/', views.StepCountView.as_view(), name='close_step1'),
path('sessions/<int:pk>/close/count/', views.StepCountView.as_view(), name='close_step1_post'),  # POST only, or merge with above
path('sessions/<int:pk>/close/remove/', views.StepRemoveView.as_view(), name='close_step2'),
path('sessions/<int:pk>/close/review/', views.StepReviewView.as_view(), name='close_step3'),
path('sessions/<int:pk>/close/post/', views.StepReviewView.as_view(), name='close_step3_post'),  # POST only
```

Simplify by handling GET/POST in each view with the same URL:
```
path('sessions/<int:pk>/close/', views.StepCountView.as_view(), name='close_step1'),
path('sessions/<int:pk>/close/remove/', views.StepRemoveView.as_view(), name='close_step2'),
path('sessions/<int:pk>/close/review/', views.StepReviewView.as_view(), name='close_step3'),
```

Each view handles its own POST.

---

## Step 4: Templates

### `backend/templates/sales/close/step1_count.html`

Extends `base.html`. Contains:

- Title bar: "Close Session — Step 1: Count Drawer"
- Session info: ID, start time, starting cash
- Table/grid with 3 columns per denomination row:
  - **Label** (e.g. "Pennies", "Nickels", etc.)
  - **Count** `<input type="number" min="0" step="1" name="count_pennies">`
  - **Amount** (auto-calculated live via Alpine.js)
- Two group sections: **Coins** group → **Bills** group
- Running totals: Coins total, Bills total, Grand total (Alpine.js computed)
- Navigation: `< Back to Dashboard` | **`Continue →`** (POST to same URL)

Alpine.js data model:
```javascript
function cashCountData(savedCounts) {
    return {
        currencyDefs: [...],
        counts: savedCounts || {},
        get breakdown() { /* map defs to computed amounts */ },
        get coinsTotal() { /* sum coin breakdown amounts */ },
        get billsTotal() { /* sum bill breakdown amounts */ },
        get grandTotal() { return this.coinsTotal + this.billsTotal; },
        init() { /* populate counts from saved */ },
    }
}
```

### `backend/templates/sales/close/step2_remove.html`

- Title bar: "Close Session — Step 2: Remove Excess Cash"
- Summary table:
  - Starting cash (from DB)
  - Total counted (from Step 1)
  - **Amount to remove = total - starting** (in red if > 0, green = 0)
- Removal breakdown table (only if `remove_amount > 0`):
  - Same denomination rows, showing:
    - Available count (from Step 1)
    - **Count to remove** (from greedy algorithm)
    - **Amount to remove**
  - Removed totals: Coins, Bills, Total
- If `removal.remaining > 0`: yellow warning "Cannot make exact change with available denominations. Remove manually. You may continue and the variance will be recorded."
- Buttons: **`← Back (Re-count)`** | **`Confirm & Continue →`** (always enabled — warning does not block)

### `backend/templates/sales/close/step3_review.html`

The final Z-Report page — **printable on US Letter (8.5×11") portrait** and **downloadable as PDF**. Two approaches for PDF:

| Approach | How | Pros | Cons |
|---|---|---|---|
| **CSS `@media print`** | US Letter @page style + `window.print()` → "Save as PDF" in browser dialog | Zero dependencies, instant | User must manually choose "Save as PDF" in print dialog |
| **Server-side PDF** | Django view using `weasyprint` or `pdfkit` to render same HTML to PDF | One-click download, consistent output | Extra dependency, rendering complexity |

**Decision: Both.** The page itself is styled for US Letter print via CSS (`@page { size: letter portrait; margin: 0.5in; }`). A "Download PDF" button triggers a server-side PDF endpoint that renders the same template with identical CSS but returns a PDF response.

Template structure:

- Title bar: "Close Session — Step 3: Review & Post"
- Z-Report content:
  - Business name, session ID, open time/date, closed by
  - P&L summary cards: Total Revenue, Gross Profit (with margin %), Transaction Count, Avg Ticket
  - Payment breakdown table (Cash/Card/Store Credit/Owner Draw with counts and amounts)
  - Cash reconciliation:
    - Starting Cash (from DB)
    - Cash Sales Today (from payment breakdown)
    - Expected Cash in Drawer
    - **Counted Cash** — per-denomination breakdown table (label, count, amount)
    - Actual Total (grand total from Step 1)
    - Variance = expected - actual
  - Removal summary: "Removed $X from drawer (starting cash $Y retained for next session)"
- Buttons:
  - **`← Back (Re-count)`** — returns to Step 2
  - **`Download PDF`** — GET to PDF endpoint (opens in new tab / downloads)
  - **`Post & Close Session`** — POST to `/close/review/`, finalizes

### PDF Endpoint

```python
# views.py
class ZReportPDFView(LoginRequiredMixin, DetailView):
    model = Session
    template_name = 'sales/close/step3_review.html'

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        # Reconstruct context same as StepReviewView
        ...
        html = render_to_string(self.template_name, context, request)
        pdf = generate_pdf(html)  # weasyprint or pdfkit
        return HttpResponse(pdf, content_type='application/pdf')
```

```python
# urls.py
path('sessions/<int:pk>/close/pdf/', views.ZReportPDFView.as_view(), name='close_pdf'),
```

### `backend/templates/sales/close/partials/` (optional)

Include small partials for re-use:
- `denomination_table.html` — reusable grid rows for count/remove/review
- `z_report_summary.html` — the P&L + payment breakdown block

---

## Step 5: Update Sidebar Link

In `base.html`, replace the modal-trigger button with a direct link:

```html
{% if active_session %}
<div class="border-t border-gray-700 mt-4 pt-4 px-4">
    <div class="text-xs text-gray-500 mb-2">Session #{{ active_session.id }}</div>
    <a href="{% url 'sales:close_step1' active_session.pk %}"
       class="flex items-center w-full px-4 py-2.5 text-sm text-orange-400 hover:bg-gray-700 hover:text-orange-300 transition rounded">
        <i class="fas fa-door-closed w-6"></i><span>Close Session</span>
    </a>
</div>
{% endif %}
```

Remove all modal HTML from `base.html`.

---

## Step 6: Delete `temp/` Files

After implementation plan is finalized:
```bash
rm -f temp/cash_counter.py temp/cash_counter.ui temp/cash_logic.py
```

---

## Execution Order

| # | Task | Files |
|---|------|-------|
| 1 | Install PDF library (`weasyprint` or `pdfkit`) | `requirements.txt` |
| 2 | Create `sales/cash_count.py` with `CURRENCY_DEFS`, `calculate_totals()`, `calculate_removal()` | `cash_count.py` |
| 3 | Add `cash_count_breakdown` JSONField to `Session` model | `models.py`, migration |
| 4 | Create `templates/sales/close/` directory with 3 step templates + partials + print CSS | 4-5 template files |
| 5 | Add `StepCountView`, `StepRemoveView`, `StepReviewView`, `ZReportPDFView` in `views.py` | `views.py` |
| 6 | Update `urls.py` with 4 routes (step1, step2, step3, pdf) | `urls.py` |
| 7 | Remove modal from `base.html`, replace sidebar link with direct URL | `base.html` |
| 8 | Delete `temp/*` files | cleanup |
| 9 | Test end-to-end flow | manual |

---

## Answered Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Store denomination breakdown? | **Yes** — use `JSONField` on `Session` for audit trail |
| 2 | Removal can't make exact change? | **Proceed with warning** — yellow alert shown, user may still confirm |
| 3 | Print behavior? | **Both** — CSS `@media print` for US Letter + server-side PDF endpoint |
| 4 | Validate negative counts? | **Confirmed** — view clamps to `max(0, int(raw))`, no negative values accepted |
