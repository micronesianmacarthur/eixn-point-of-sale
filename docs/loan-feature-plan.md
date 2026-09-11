# Loan Feature — Implementation Plan

## Overview

A dedicated loan management module separate from the sales checkout. Users can disburse loans to customers from a dedicated loan checkout page. Interest accrues daily based on a configurable annual rate stored in `SystemSetting`. Loan repayments are processed on the loan detail page.

---

## Phase 1: Data Model

### 1.1 Create `loans` app

```bash
python manage.py startapp loans
```

Register in `core/settings.py` (`INSTALLED_APPS`).

### 1.2 `loans/models.py`

```python
from django.db import models
from django.conf import settings
from django.utils import timezone


class Loan(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        PAID = 'PAID', 'Paid'
        WRITTEN_OFF = 'WRITTEN_OFF', 'Written Off'

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='loans'
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    principal = models.DecimalField(max_digits=12, decimal_places=2)
    daily_rate = models.DecimalField(
        max_digits=7, decimal_places=6,
        help_text='Annual rate / 365, stored at origination'
    )
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def days_since_issue(self):
        return (timezone.now().date() - self.issued_at.date()).days

    def accrued_interest(self):
        return self.principal * self.daily_rate * max(self.days_since_issue(), 0)

    def outstanding(self):
        return max(self.principal + self.accrued_interest() - self.total_paid, 0)
```

### 1.3 Add `LOAN_INTEREST_RATE` to `SystemSetting`

Seed via a new migration in `core/migrations/`:

```python
from django.db import migrations
from core.models import SystemSetting


def seed_loan_rate(apps, schema_editor):
    SystemSetting.objects.get_or_create(
        key='LOAN_INTEREST_RATE',
        defaults={
            'value': '0.10',
            'description': 'Annual interest rate for loans (e.g. 0.10 = 10%%)',
        },
    )

def reverse(apps, schema_editor):
    SystemSetting.objects.filter(key='LOAN_INTEREST_RATE').delete()

class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [migrations.RunPython(seed_loan_rate, reverse)]
```

### 1.4 Run migrations

```bash
python manage.py makemigrations loans && python manage.py migrate
```

---

## Phase 2: Service Layer

### 2.1 `loans/services.py`

```python
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from core.models import SystemSetting
from accounting.services import write_ledger_entry


@transaction.atomic
def disburse_loan(customer, principal, operator_user):
    """
    Create a loan, update customer balance, write ledger entry.

    Pseudocode:
      1. Load LOAN_INTEREST_RATE from SystemSetting (default 0.10)
      2. daily_rate = annual_rate / Decimal('365')
      3. loan = Loan.objects.create(
           customer=customer,
           issued_by=operator_user,
           principal=principal,
           daily_rate=daily_rate,
           status=Loan.Status.ACTIVE,
           issued_at=timezone.now(),
         )
      4. customer.cached_balance = F('cached_balance') + principal
      5. customer.save(update_fields=['cached_balance'])
      6. write_ledger_entry(
           session=get_active_session(),
           transaction=loan,         # or None, depends on accounting setup
           amount=principal,
           entry_type='LOAN_DISBURSEMENT',
           description=f'Loan #{loan.id} disbursed to {customer.name}',
         )
      7. return loan
    """
    annual_rate_setting = SystemSetting.objects.filter(key='LOAN_INTEREST_RATE').first()
    annual_rate = Decimal(annual_rate_setting.value) if annual_rate_setting else Decimal('0.10')
    daily_rate = annual_rate / Decimal('365')

    loan = Loan.objects.create(
        customer=customer,
        issued_by=operator_user,
        principal=principal,
        daily_rate=daily_rate,
        status=Loan.Status.ACTIVE,
    )

    Customer.objects.filter(id=customer.id).update(
        cached_balance=models.F('cached_balance') + principal
    )

    write_ledger_entry(
        session=None,  # resolve session if applicable
        transaction=None,
        amount=principal,
        entry_type='LOAN_DISBURSEMENT',
        description=f'Loan #{loan.id} disbursed to {customer.name}',
    )

    return loan


@transaction.atomic
def process_repayment(loan, amount, payment_type, operator_user):
    """
    Record a payment against a loan.

    Pseudocode:
      1. Validate: loan.status == ACTIVE, else raise ValueError
      2. Validate: amount > 0, else raise ValueError
      3. outstanding = loan.outstanding()
      4. Validate: amount <= outstanding, else raise ValueError("Overpayment")
      5. Lock loan row: Loan.objects.select_for_update().get(id=loan.id)
      6. loan.total_paid = F('total_paid') + amount
      7. loan.refresh_from_db()
      8. new_outstanding = loan.outstanding()
      9. if new_outstanding <= 0:
           loan.status = PAID
           loan.paid_at = timezone.now()
      10. loan.save()
      11. customer.cached_balance = F('cached_balance') - amount
      12. customer.save(update_fields=['cached_balance'])
      13. write_ledger_entry(
            entry_type='LOAN_REPAYMENT',
            amount=-amount,
            description=f'Repayment of ${amount} on Loan #{loan.id}',
          )
      14. return loan
    """
    if loan.status != Loan.Status.ACTIVE:
        raise ValueError('Loan is not active')

    if amount <= 0:
        raise ValueError('Amount must be positive')

    outstanding = loan.outstanding()
    if amount > outstanding:
        raise ValueError(f'Amount exceeds outstanding balance of ${outstanding:.2f}')

    loan = Loan.objects.select_for_update().get(id=loan.id)
    loan.total_paid += amount

    if loan.outstanding() <= 0:
        loan.status = Loan.Status.PAID
        loan.paid_at = timezone.now()

    loan.save()

    Customer.objects.filter(id=loan.customer_id).update(
        cached_balance=models.F('cached_balance') - amount
    )

    write_ledger_entry(
        session=None,
        transaction=None,
        amount=-amount,
        entry_type='LOAN_REPAYMENT',
        description=f'Payment of ${amount} on Loan #{loan.id}',
    )

    return loan


def get_outstanding(loan):
    """
    Compute current outstanding balance.
    """
    return max(loan.principal + loan.accrued_interest() - loan.total_paid, 0)


def annotate_outstanding(queryset):
    """
    Annotate a Loan queryset with computed outstanding balance.
    Since Django can't easily annotate with Python method calls,
    we fetch all and compute in Python for small lists,
    or use a database-side expression for larger datasets.

    Pseudocode:
      For each loan in queryset:
        days = (today - loan.issued_at.date()).days
        interest = loan.principal * loan.daily_rate * max(days, 0)
        loan._outstanding = loan.principal + interest - loan.total_paid
      return queryset
    """
    today = timezone.now().date()
    for loan in queryset:
        days = max((today - loan.issued_at.date()).days, 0)
        interest = loan.principal * loan.daily_rate * days
        loan._outstanding = max(loan.principal + interest - loan.total_paid, 0)
    return queryset
```

---

## Phase 3: Views

### 3.1 `loans/views.py`

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import FormView, ListView, DetailView, View
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from .models import Loan
from .services import disburse_loan, process_repayment


class LoanListView(LoginRequiredMixin, ListView):
    """
    GET /loans/
    List all loans, filterable by status.

    Pseudocode:
      1. qs = Loan.objects.select_related('customer', 'issued_by')
      2. status = request.GET.get('status', 'ACTIVE')
      3. if status != 'ALL': qs = qs.filter(status=status)
      4. qs = qs.order_by('-issued_at')
      5. annotate_outstanding(qs)   # sets loan._outstanding
      6. context = {
           'loans': qs,
           'current_status': status,
           'status_choices': Loan.Status.choices,
         }
      7. render template
    """
    model = Loan
    template_name = 'loans/list.html'
    context_object_name = 'loans'

    def get_queryset(self):
        qs = Loan.objects.select_related('customer', 'issued_by')
        status = self.request.GET.get('status', 'ACTIVE')
        if status != 'ALL':
            qs = qs.filter(status=status)
        return qs.order_by('-issued_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_status'] = self.request.GET.get('status', 'ACTIVE')
        loans = annotate_outstanding(list(context['loans']))
        context['loans'] = loans
        return context


class LoanCreateView(LoginRequiredMixin, FormView):
    """
    GET/POST /loans/create/
    Loan checkout page.

    Pseudocode:
      GET:
        context = {
          'annual_rate': SystemSetting LOAN_INTEREST_RATE,
          'daily_rate': annual_rate / 365,
        }
        render create.html

      POST:
        1. Validate: customer_id in POST
        2. Validate: principal = Decimal(POST['principal']) > 0
        3. Load customer = Customer.objects.get(id=customer_id)
        4. loan = disburse_loan(customer, principal, request.user)
        5. messages.success(request, f'Loan #{loan.id} disbursed')
        6. redirect to loan_detail
    """
    template_name = 'loans/create.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rate = SystemSetting.objects.filter(key='LOAN_INTEREST_RATE').first()
        annual = Decimal(rate.value) if rate else Decimal('0.10')
        context['annual_rate'] = annual
        context['daily_rate'] = annual / Decimal('365')
        return context

    def post(self, request, *args, **kwargs):
        from customers.models import Customer
        from decimal import Decimal, InvalidOperation

        customer_id = request.POST.get('customer_id')
        principal_str = request.POST.get('principal', '').strip()

        if not customer_id:
            return self.form_invalid(...)   # customer required

        try:
            principal = Decimal(principal_str)
        except InvalidOperation:
            return self.form_invalid(...)   # invalid amount

        if principal <= 0:
            return self.form_invalid(...)   # must be positive

        customer = get_object_or_404(Customer, id=customer_id)
        loan = disburse_loan(customer, principal, request.user)

        messages.success(request, f'Loan #{loan.id} disbursed to {customer.name}')
        return HttpResponseRedirect(reverse('loans:loan_detail', args=[loan.id]))


class LoanDetailView(LoginRequiredMixin, DetailView):
    """
    GET /loans/<pk>/
    Show single loan with outstanding balance and repayment form.

    Pseudocode:
      1. loan = Loan.objects.select_related('customer', 'issued_by')
      2. loan.outstanding computed via loan.outstanding() method
      3. context = {
           'loan': loan,
           'outstanding': loan.outstanding(),
           'payment_types': [CASH, CARD, STORE_CREDIT],
         }
      4. render detail.html
    """
    model = Loan
    template_name = 'loans/detail.html'
    context_object_name = 'loan'
    queryset = Loan.objects.select_related('customer', 'issued_by')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['outstanding'] = self.object.outstanding()
        return context


class LoanRepayView(LoginRequiredMixin, View):
    """
    POST /loans/<pk>/repay/
    HTMX partial — process a repayment.

    Pseudocode:
      1. loan = get_object_or_404(Loan, id=pk)
      2. amount = Decimal(request.POST.get('amount', '0'))
      3. payment_type = request.POST.get('payment_type', 'CASH')
      4. try:
           loan = process_repayment(loan, amount, payment_type, request.user)
         except ValueError as e:
           return HttpResponse(str(e), status=400)
      5. html = render_to_string('loans/partials/loan_detail_content.html', {
           'loan': loan,
           'outstanding': loan.outstanding(),
         })
      6. return HttpResponse(html)
    """
    def post(self, request, pk):
        from decimal import Decimal, InvalidOperation

        loan = get_object_or_404(Loan, id=pk)
        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except InvalidOperation:
            return HttpResponse('Invalid amount', status=400)

        payment_type = request.POST.get('payment_type', 'CASH')

        try:
            loan = process_repayment(loan, amount, payment_type, request.user)
        except ValueError as e:
            return HttpResponse(str(e), status=400)

        html = render_to_string('loans/partials/loan_detail_content.html', {
            'loan': loan,
            'outstanding': loan.outstanding(),
        })
        return HttpResponse(html)


class LoanCustomerSearchView(LoginRequiredMixin, View):
    """
    GET /loans/customer-search/?q=...
    HTMX partial — search customers by name for the create form.

    Pseudocode:
      1. q = request.GET.get('q', '').strip()
      2. if len(q) < 2: return empty results
      3. customers = Customer.objects.filter(name__icontains=q)[:10]
      4. html = render_to_string('loans/partials/customer_search_results.html', {
           'customers': customers,
         })
      5. return HttpResponse(html)
    """
    def get(self, request):
        from customers.models import Customer

        q = request.GET.get('q', '').strip()
        customers = Customer.objects.filter(name__icontains=q)[:10] if len(q) >= 2 else []
        html = render_to_string('loans/partials/customer_search_results.html', {
            'customers': customers,
        })
        return HttpResponse(html)
```

### 3.2 Authorization

All views use `LoginRequiredMixin`. Add `ManagerOrAdminMixin` from `inventory.mixins` if loan disbursement should require manager privileges.

---

## Phase 4: URLs

### 4.1 `loans/urls.py`

```python
from django.urls import path
from . import views

app_name = 'loans'

urlpatterns = [
    path('', views.LoanListView.as_view(), name='loan_list'),
    path('create/', views.LoanCreateView.as_view(), name='loan_create'),
    path('customer-search/', views.LoanCustomerSearchView.as_view(), name='customer_search'),
    path('<int:pk>/', views.LoanDetailView.as_view(), name='loan_detail'),
    path('<int:pk>/repay/', views.LoanRepayView.as_view(), name='loan_repay'),
]
```

### 4.2 Wire into `core/urls.py`

```python
path('loans/', include('loans.urls')),
```

---

## Phase 5: Templates

### 5.1 `templates/loans/create.html`

```html
{% extends 'base.html' %}
{% block content %}

<h2>Disburse Loan</h2>

<form method="post">
  {% csrf_token %}

  <!-- Customer Search (HTMX) -->
  <label>Customer</label>
  <input type="text" id="customerSearch" name="customer_q"
         placeholder="Search customer name..."
         hx-get="{% url 'loans:customer_search' %}"
         hx-target="#customerResults"
         hx-trigger="keyup changed delay:300ms">
  <div id="customerResults"></div>
  <!-- Hidden input set by JS when a customer is selected -->
  <input type="hidden" name="customer_id" id="customerId">

  <!-- Loan Amount -->
  <label>Loan Amount ($)</label>
  <input type="number" name="principal" step="0.01" min="0" required>

  <!-- Terms Summary (read-only) -->
  <div class="bg-gray-50 p-4 rounded">
    <p>Annual interest rate: <strong>{{ annual_rate|floatformat:2 }}%</strong></p>
    <p>Daily rate: <strong>{{ daily_rate|floatformat:6 }}</strong></p>
    <p class="text-sm text-gray-500">Interest accrues daily from disbursement date.</p>
  </div>

  <button type="submit" class="bg-blue-600 text-white px-6 py-2 rounded">
    Disburse Loan
  </button>
</form>

<script>
  // When a customer result is clicked, populate the hidden input
  document.addEventListener('click', function(e) {
    if (e.target.dataset.customerId) {
      document.getElementById('customerId').value = e.target.dataset.customerId;
    }
  });
</script>

{% endblock %}
```

### 5.2 `templates/loans/list.html`

Key UI elements:
- Status filter tabs: `?status=ACTIVE` | `?status=PAID` | `?status=ALL`
- Table with columns: Customer, Principal, Outstanding, Daily Interest, Days Active, Status, Actions
- Outstanding computed via `loan._outstanding` (set by `annotate_outstanding()`)
- Status badges: blue for ACTIVE, green for PAID, gray for WRITTEN_OFF
- Empty state if no loans

```html
<!-- Filter tabs -->
<div class="flex gap-2 mb-4">
  <a href="?status=ACTIVE" class="{% if current_status == 'ACTIVE' %}bg-blue-600 text-white{% else %}bg-gray-100{% endif %} px-4 py-2 rounded">Active</a>
  <a href="?status=PAID" class="...">Paid</a>
  <a href="?status=ALL" class="...">All</a>
</div>

<!-- Table -->
<table>
  <thead>
    <tr>
      <th>Customer</th>
      <th>Principal</th>
      <th>Outstanding</th>
      <th>Daily Interest</th>
      <th>Days</th>
      <th>Status</th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    {% for loan in loans %}
    <tr>
      <td>{{ loan.customer.name }}</td>
      <td>${{ loan.principal }}</td>
      <td>${{ loan._outstanding|floatformat:2 }}</td>
      <td>${{ loan.principal|multiply:loan.daily_rate|floatformat:4 }}</td>
      <td>{{ loan.days_since_issue }}</td>
      <td>{% status_badge loan.status %}</td>
      <td><a href="{% url 'loans:loan_detail' loan.id %}">View</a></td>
    </tr>
    {% empty %}
    <tr><td colspan="7">No loans found.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

### 5.3 `templates/loans/detail.html`

```html
{% extends 'base.html' %}
{% block content %}

<h2>Loan #{{ loan.id }}</h2>

<!-- Customer info -->
<p>Customer: {{ loan.customer.name }}</p>
<p>Issued by: {{ loan.issued_by.get_full_name }}</p>
<p>Issued: {{ loan.issued_at|date:"M j, Y" }}</p>
<p>Status: {% status_badge loan.status %}</p>

<!-- Balance summary -->
<div id="loanDetailContent">
  {% include 'loans/partials/loan_detail_content.html' %}
</div>

<!-- Repayment form (HTMX) -->
{% if loan.status == 'ACTIVE' %}
<form hx-post="{% url 'loans:loan_repay' loan.id %}"
      hx-target="#loanDetailContent"
      hx-swap="outerHTML">
  {% csrf_token %}
  <label>Payment Amount ($)</label>
  <input type="number" name="amount" step="0.01" min="0" max="{{ outstanding }}" required>
  <label>Payment Type</label>
  <select name="payment_type">
    <option value="CASH">Cash</option>
    <option value="CARD">Card</option>
    <option value="STORE_CREDIT">Store Credit</option>
  </select>
  <button type="submit">Make Payment</button>
</form>
{% endif %}

{% endblock %}
```

### 5.4 `templates/loans/partials/loan_detail_content.html`

```html
<div id="loanDetailContent" class="grid grid-cols-3 gap-4 my-4">
  <div class="bg-blue-50 p-4 rounded">
    <span class="text-sm text-gray-500">Principal</span>
    <p class="text-xl font-bold">${{ loan.principal }}</p>
  </div>
  <div class="bg-yellow-50 p-4 rounded">
    <span class="text-sm text-gray-500">Accrued Interest</span>
    <p class="text-xl font-bold">${{ loan.accrued_interest|floatformat:2 }}</p>
  </div>
  <div class="bg-green-50 p-4 rounded">
    <span class="text-sm text-gray-500">Outstanding</span>
    <p class="text-xl font-bold">${{ outstanding|floatformat:2 }}</p>
  </div>
</div>
{% if messages %}
<div class="messages">
  {% for msg in messages %}
  <div class="alert alert-{{ msg.tags }}">{{ msg }}</div>
  {% endfor %}
</div>
{% endif %}
```

### 5.5 `templates/loans/partials/customer_search_results.html`

```html
<div id="customerResults" class="border rounded mt-1 max-h-48 overflow-y-auto">
  {% for c in customers %}
  <button type="button"
          data-customer-id="{{ c.id }}"
          data-customer-name="{{ c.name }}"
          class="block w-full text-left px-3 py-2 hover:bg-blue-50 text-sm"
          onclick="document.getElementById('customerId').value='{{ c.id }}';
                   document.getElementById('customerSearch').value='{{ c.name }}';
                   this.closest('#customerResults').innerHTML='';">
    {{ c.name }}
    {% if c.phone %}<span class="text-gray-400 text-xs ml-2">{{ c.phone }}</span>{% endif %}
  </button>
  {% empty %}
  <div class="px-3 py-2 text-gray-400 text-sm">No customers found.</div>
  {% endfor %}
</div>
```

---

## Phase 6: Navigation & Integration

### 6.1 `base.html`

Add a "Loans" nav link:

```html
<a href="{% url 'loans:loan_list' %}"
   class="{% if request.resolver_match.app_name == 'loans' %}active{% endif %}">
  <i class="fas fa-hand-holding-usd mr-2"></i> Loans
</a>
```

### 6.2 Customer admin detail (optional)

If `customers/templates/customers/detail.html` exists, add a "Loans" section:

```html
<h3>Active Loans</h3>
{% for loan in customer.loans.all %}
  {% if loan.status == 'ACTIVE' %}
  <a href="{% url 'loans:loan_detail' loan.id %}">
    Loan #{{ loan.id }} — ${{ loan.outstanding|floatformat:2 }} outstanding
  </a>
  {% endif %}
{% empty %}
  <p class="text-gray-400">No active loans.</p>
{% endfor %}
```

---

## Phase 7: Edge Cases & Guardrails

| Scenario | Handling |
|---|---|
| Customer has no credit limit set | Allow loan up to a configurable `MAX_LOAN_AMOUNT` in SystemSetting, or fall back to manager override with PIN |
| Loan amount exceeds limit | Show warning in UI, require manager PIN confirmation before disbursing |
| Daily interest below $0.0001 | Clamp to 0 at service layer |
| Partial repayment | Track as `total_paid`, do not mark PAID until `outstanding() <= 0` |
| Negative outstanding computation | Clamp to 0 in `Loan.outstanding()` method |
| Concurrent repayment race | Use `select_for_update()` in `process_repayment()` |
| Voiding a disbursement | Set status to `WRITTEN_OFF`, reverse customer balance adjustment |
| Customer deleted before loan repaid | FK is PROTECT — cannot delete customer with active loans |
| Loan repaid with STORE_CREDIT | Validate `allow_pay_later` and credit limit before processing |
| Daily interest on leap year | 365-day year convention (consistent, regardless of leap year) |

---

## Future Enhancements (Not in Initial Scope)

| Feature | Description |
|---|---|
| Loan approval workflow | Manager must approve loans above a threshold via PIN confirmation |
| Late fees | Configurable SystemSetting `LOAN_LATE_FEE_DAILY`, charged after N days overdue |
| Amortization schedule | Display a table of projected payments (principal + interest breakdown per period) |
| SMS/Email reminders | Automated notification when loan is X days from due or overdue |
| Loan dashboard | Aggregate stats: total lent, default rate, interest earned MTD/YTD |
| Bulk CSV export | Export loan portfolio for external accounting |
| Loan products | Different loan types with different rates (e.g., short-term, long-term) |
| Collateral tracking | Optional field to record collateral items for secured loans |

---

## Files Changed Summary

| File | Action |
|---|---|
| `loans/__init__.py` | Create |
| `loans/models.py` | Create |
| `loans/services.py` | Create |
| `loans/views.py` | Create |
| `loans/urls.py` | Create |
| `loans/admin.py` | Create |
| `loans/apps.py` | Create (auto-generated by startapp) |
| `core/settings.py` | Add `'loans'` to INSTALLED_APPS |
| `core/urls.py` | Add `path('loans/', include('loans.urls'))` |
| `core/migrations/XXXX_seed_loan_rate.py` | Create (new migration) |
| `templates/loans/create.html` | Create |
| `templates/loans/list.html` | Create |
| `templates/loans/detail.html` | Create |
| `templates/loans/partials/loan_detail_content.html` | Create |
| `templates/loans/partials/customer_search_results.html` | Create |
| `templates/base.html` | Modify (add nav link) |

**Total new files:** ~16 | **Modified files:** 3 | **Estimated effort:** 2–3 days
