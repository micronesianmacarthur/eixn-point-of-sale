from decimal import Decimal

from django.db import models, transaction

from .models import Customer


@transaction.atomic
def award_loyalty_points(*, customer_id, total, payment_type):
    if payment_type == 'STORE_CREDIT':
        return 0
    customer = Customer.objects.select_for_update().get(id=customer_id)
    if not customer.loyalty_enabled:
        return 0
    points = int(Decimal(str(total)) / Decimal('10'))
    Customer.objects.filter(id=customer_id).update(
        loyalty_points=models.F('loyalty_points') + points
    )
    return points


@transaction.atomic
def adjust_customer_balance(customer_id, amount):
    customer = Customer.objects.select_for_update().get(id=customer_id)
    customer.cached_balance += amount
    customer.save(update_fields=['cached_balance'])
    return customer


@transaction.atomic
def process_customer_payment(*, customer_id, amount):
    customer = Customer.objects.select_for_update().get(id=customer_id)
    customer.cached_balance -= amount
    customer.save(update_fields=['cached_balance'])
    return customer
