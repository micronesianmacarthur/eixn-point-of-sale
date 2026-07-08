from django.db import models

from customers.models import Customer
from inventory.models import Product
from users.models import User


class Session(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        POSTED = 'POSTED', 'Posted'

    opened_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='sessions_opened')
    closed_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='sessions_closed')
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    starting_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    ending_cash_expected = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    ending_cash_actual = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cash_count_breakdown = models.JSONField(null=True, blank=True,
        help_text='Per-denomination counts entered at session close')
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)

    def __str__(self):
        return f'Session {self.id} ({self.get_status_display()})'


class Transaction(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        POSTED = 'POSTED', 'Posted'
        VOIDED = 'VOIDED', 'Voided'

    class PaymentType(models.TextChoices):
        CASH = 'CASH', 'Cash'
        CARD = 'CARD', 'Card'
        STORE_CREDIT = 'STORE_CREDIT', 'Store Credit'
        OWNER_DRAW = 'OWNER_DRAW', 'Owner Draw'

    session = models.ForeignKey(Session, on_delete=models.RESTRICT, related_name='transactions')
    cashier = models.ForeignKey(User, on_delete=models.PROTECT, related_name='transactions')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    payment_type = models.CharField(max_length=12, choices=PaymentType.choices, default=PaymentType.CASH)
    payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.POSTED)
    created_at = models.DateTimeField(auto_now_add=True)
    transaction_date = models.DateTimeField(help_text='Actual business date (user-inputtable for offline recovery)')

    def __str__(self):
        return f'Txn {self.id} (${self.total_amount})'


class TransactionLineItem(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.RESTRICT, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transaction_items')
    quantity_sold = models.DecimalField(max_digits=10, decimal_places=3)
    price_at_sale = models.DecimalField(max_digits=12, decimal_places=2)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
