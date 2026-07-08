from django.contrib import admin

from .models import Session, Transaction, TransactionLineItem


class TransactionLineItemInline(admin.TabularInline):
    model = TransactionLineItem
    extra = 0
    readonly_fields = ('product', 'quantity_sold', 'price_at_sale', 'cost_price')


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'opened_by', 'closed_by', 'start_time', 'end_time', 'starting_cash')
    list_filter = ('status',)
    actions = ['delete_selected']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'cashier', 'customer', 'total_amount', 'payment_type', 'status', 'transaction_date')
    list_filter = ('status', 'payment_type', 'session')
    inlines = [TransactionLineItemInline]
    actions = ['delete_selected']


@admin.register(TransactionLineItem)
class TransactionLineItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction', 'product', 'quantity_sold', 'price_at_sale')
    actions = ['delete_selected']
