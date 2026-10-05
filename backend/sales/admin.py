from django.contrib import admin

from .models import Payment, Session, Transaction, TransactionLineItem


class TransactionLineItemInline(admin.TabularInline):
    model = TransactionLineItem
    extra = 0
    readonly_fields = ('product', 'quantity_sold', 'price_at_sale', 'cost_price')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'opened_by', 'closed_by', 'start_time', 'end_time', 'starting_cash')
    list_filter = ('status',)
    actions = ['delete_selected']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'cashier', 'customer', 'total_amount', 'payments_summary', 'status', 'transaction_date')
    list_filter = ('status', 'payments__payment_type', 'session')
    inlines = [TransactionLineItemInline, PaymentInline]
    actions = ['delete_selected']

    @admin.display(description='Payments')
    def payments_summary(self, obj):
        return ', '.join(f'{p.get_payment_type_display()} {p.amount}' for p in obj.payments.all()) or '—'


@admin.register(TransactionLineItem)
class TransactionLineItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction', 'product', 'quantity_sold', 'price_at_sale')
    actions = ['delete_selected']
