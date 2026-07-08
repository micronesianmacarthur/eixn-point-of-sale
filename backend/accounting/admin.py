from django.contrib import admin

from .models import Ledger, OwnerCapitalLedger


@admin.register(OwnerCapitalLedger)
class OwnerCapitalLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner_user_id', 'amount', 'transaction_type', 'reference_receipt_id', 'timestamp')
    list_filter = ('transaction_type',)
    actions = ['delete_selected']


@admin.register(Ledger)
class LedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'transaction', 'logged_by', 'amount', 'entry_type', 'description', 'created_at')
    list_filter = ('entry_type', 'session')
    actions = ['delete_selected']
