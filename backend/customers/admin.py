from django.contrib import admin

from .models import CreditProfile, Customer


class CreditProfileInline(admin.StackedInline):
    model = CreditProfile
    can_delete = False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'cached_balance', 'credit_limit', 'allow_pay_later', 'is_owner', 'loyalty_points')
    list_filter = ('allow_pay_later', 'is_owner', 'loyalty_enabled')
    inlines = [CreditProfileInline]
    actions = ['delete_selected']


@admin.register(CreditProfile)
class CreditProfileAdmin(admin.ModelAdmin):
    list_display = ('customer', 'current_balance', 'credit_limit', 'settlement_period_days')
    actions = ['delete_selected']
