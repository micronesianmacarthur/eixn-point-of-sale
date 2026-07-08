from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from customers.models import Customer
from sales.models import Session, Transaction

from .models import Ledger, OwnerCapitalLedger


def write_ledger_entry(*, session, transaction, amount, entry_type, logged_by, description=''):
    Ledger.objects.create(
        session=session,
        transaction=transaction,
        amount=amount,
        entry_type=entry_type,
        logged_by=logged_by,
        description=description,
    )


@transaction.atomic
def equity_offset(*, admin_user, customer, amount):
    profile = customer.credit_profile
    profile.current_balance = Decimal('0.00')
    profile.save(update_fields=['current_balance'])

    OwnerCapitalLedger.objects.create(
        owner_user_id=customer.id,
        amount=Decimal(str(amount)),
        transaction_type=OwnerCapitalLedger.TransactionType.CONTRIBUTION,
    )

    session = Session.objects.filter(status=Session.Status.OPEN).first()
    if not session:
        raise ValueError('No active session to record equity offset.')

    Ledger.objects.create(
        session=session,
        transaction=None,
        logged_by=admin_user,
        amount=Decimal(str(amount)),
        entry_type=Ledger.EntryType.CORRECTION,
        description=f'Equity offset for {customer.name}',
    )


@transaction.atomic
def process_policy_capped_owner_draw(*, owner_customer_id, operator_user, contribution_amount):
    if contribution_amount <= 0:
        return None

    customer = Customer.objects.select_for_update().get(id=owner_customer_id)
    if not customer.is_owner or customer.cached_balance <= 0:
        return None

    draw_amount = min(customer.cached_balance, Decimal(str(contribution_amount)))

    session = Session.objects.filter(status=Session.Status.OPEN).first()
    if not session:
        return None

    OwnerCapitalLedger.objects.create(
        owner_user_id=owner_customer_id,
        amount=draw_amount,
        transaction_type=OwnerCapitalLedger.TransactionType.DRAW,
        reference_receipt_id=None,
    )

    Transaction.objects.create(
        session=session,
        cashier=operator_user,
        customer=customer,
        total_amount=-draw_amount,
        payment_type=Transaction.PaymentType.OWNER_DRAW,
        payment_amount=draw_amount,
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
    )

    customer.cached_balance -= draw_amount
    customer.save(update_fields=['cached_balance'])

    return draw_amount


@transaction.atomic
def process_owner_contribution(*, session, owner_customer, operator_user, contribution_amount):
    if contribution_amount <= 0:
        return None

    customer = Customer.objects.select_for_update().get(id=owner_customer.id)
    if not customer.is_owner:
        return None

    draw_amount = min(customer.cached_balance, Decimal(str(contribution_amount)))

    OwnerCapitalLedger.objects.create(
        owner_user_id=owner_customer.id,
        amount=Decimal(str(contribution_amount)),
        transaction_type=OwnerCapitalLedger.TransactionType.CONTRIBUTION,
    )

    if draw_amount > 0:
        OwnerCapitalLedger.objects.create(
            owner_user_id=owner_customer.id,
            amount=draw_amount,
            transaction_type=OwnerCapitalLedger.TransactionType.DRAW,
        )

        Transaction.objects.create(
            session=session,
            cashier=operator_user,
            customer=customer,
            total_amount=-draw_amount,
            payment_type=Transaction.PaymentType.OWNER_DRAW,
            payment_amount=draw_amount,
            status=Transaction.Status.POSTED,
            transaction_date=timezone.now(),
        )

        customer.cached_balance -= draw_amount
        customer.save(update_fields=['cached_balance'])

    return draw_amount
