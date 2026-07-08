from django.db import models

from sales.models import Session, Transaction
from users.models import User


class OwnerCapitalLedger(models.Model):
    class TransactionType(models.TextChoices):
        CONTRIBUTION = 'CONTRIBUTION', 'Contribution'
        DRAW = 'DRAW', 'Draw'

    owner_user_id = models.IntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=12, choices=TransactionType.choices)
    reference_receipt_id = models.IntegerField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_transaction_type_display()} ${self.amount}'


class Ledger(models.Model):
    class EntryType(models.TextChoices):
        SALE = 'SALE', 'Sale'
        EXPENSE = 'EXPENSE', 'Expense'
        PAYMENT = 'PAYMENT', 'Payment'
        CORRECTION = 'CORRECTION', 'Correction'
        OWNER_DRAW = 'OWNER_DRAW', 'Owner Draw'

    session = models.ForeignKey(Session, on_delete=models.RESTRICT, related_name='ledger_entries')
    transaction = models.ForeignKey(Transaction, on_delete=models.RESTRICT, null=True, blank=True, related_name='ledger_entries')
    logged_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ledger_entries')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    entry_type = models.CharField(max_length=12, choices=EntryType.choices)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.get_entry_type_display()} ${self.amount}'
