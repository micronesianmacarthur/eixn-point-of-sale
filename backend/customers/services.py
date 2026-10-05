from decimal import Decimal

from django.db import models, transaction

from .models import Customer


@transaction.atomic
def award_loyalty_points(*, customer_id, amount):
    """Award 1 point per $10 actually paid in real money.

    Callers pass the non-credit portion of a sale's total, so a fully
    store-credit sale still earns nothing — the rule the old `payment_type`
    check used to express.
    """
    amount = Decimal(str(amount))
    if amount <= 0:
        return 0
    customer = Customer.objects.select_for_update().get(id=customer_id)
    if not customer.loyalty_enabled:
        return 0
    points = int(amount / Decimal('10'))
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
