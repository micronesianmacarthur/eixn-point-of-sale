from decimal import ROUND_HALF_UP, Decimal

from django.db import models, transaction
from django.utils import timezone

from accounting.models import Ledger, OwnerCapitalLedger
from accounting.services import write_ledger_entry
from customers.models import Customer
from customers.services import award_loyalty_points
from inventory.models import Product
from inventory.services import deduct_composite

from .models import Payment, Session, Transaction, TransactionLineItem

CASH = Payment.PaymentType.CASH
CARD = Payment.PaymentType.CARD
STORE_CREDIT = Payment.PaymentType.STORE_CREDIT
OWNER_DRAW = Payment.PaymentType.OWNER_DRAW

CENTS = Decimal('0.01')
ZERO = Decimal('0.00')

# Types the checkout screen can tender. OWNER_DRAW is deliberately excluded: an
# owner draw is only ever created by the accounting flows, never by a cashier.
TENDERABLE_TYPES = (CASH, CARD, STORE_CREDIT)


def to_cents(value):
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def normalize_payments(payments, total, customer=None):
    """Validate a split tender and return it as [(type, Decimal amount)].

    The client drives an auto-completing flow, so its arithmetic is treated as
    untrusted: every leg is re-quantized here and the split must cover `total`
    exactly once rounding is applied. Non-cash legs may not exceed the balance
    remaining at the point they are applied, because change can only come out of
    a cash leg. Re-tendering a type merges into the existing leg, keeping the
    one-row-per-type invariant rather than dead-ending the cashier.
    """
    legs = []
    remaining = total

    for entry in payments:
        payment_type = entry.get('payment_type')
        if payment_type not in TENDERABLE_TYPES:
            raise ValueError(f'Invalid payment type: {payment_type}')

        amount = to_cents(entry.get('amount', ZERO))
        if amount <= ZERO:
            raise ValueError('Payment amount must be greater than zero.')

        if payment_type == STORE_CREDIT and customer is None:
            raise ValueError('Store credit requires a customer.')

        existing = next((i for i, (t, _) in enumerate(legs) if t == payment_type), None)
        if existing is not None:
            amount += legs[existing][1]

        if amount > remaining and payment_type != CASH:
            raise ValueError(
                f'{Payment.PaymentType(payment_type).label} payment of ${amount:.2f} '
                f'exceeds the ${remaining:.2f} balance due. Change can only be given on cash.'
            )

        if existing is not None:
            legs[existing] = (payment_type, amount)
        else:
            legs.append((payment_type, amount))
        remaining -= amount

    if not legs:
        raise ValueError('At least one payment is required.')

    tendered = sum((amount for _, amount in legs), ZERO)
    if tendered < total:
        raise ValueError(
            f'Payments total ${tendered:.2f} but the sale is ${total:.2f} — '
            f'${total - tendered:.2f} still due.'
        )

    return legs


@transaction.atomic
def process_checkout(*, session_id, items, payments, customer_id=None, operator_user=None):
    session = Session.objects.select_for_update().get(id=session_id, status=Session.Status.OPEN)

    product_ids = sorted(item['product_id'] for item in items)
    products = {
        p.id: p
        for p in Product.objects.select_for_update().filter(id__in=product_ids)
    }

    customer = None
    if customer_id:
        customer = Customer.objects.select_for_update().get(id=customer_id)

    txn_items = []
    total = Decimal('0.00')
    for item in items:
        product = products[item['product_id']]
        qty = Decimal(str(item['quantity']))
        price_override = item.get('price_override')
        price = Decimal(str(price_override)) if price_override is not None else (product.discount_price if product.is_on_sale and product.discount_price is not None else product.retail_price)
        line_total = to_cents(price * qty)
        total += line_total

        if not product.is_service and product.stock_quantity < qty:
            raise ValueError(f'Insufficient stock for {product.name}')

        txn_items.append({
            'product': product,
            'quantity': qty,
            'cost_price': product.cost_price,
            'price_charged': price,
        })

    if payments:
        legs = normalize_payments(payments, total, customer=customer)
    else:
        legs = [(CASH, total)]

    credit_amount = sum((amount for t, amount in legs if t == STORE_CREDIT), ZERO)

    txn = Transaction.objects.create(
        session=session,
        cashier=operator_user or session.opened_by,
        customer=customer,
        total_amount=total,
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
    )

    Payment.objects.bulk_create([
        Payment(transaction=txn, payment_type=t, amount=amount)
        for t, amount in legs
    ])

    for ti in txn_items:
        TransactionLineItem.objects.create(
            transaction=txn,
            product=ti['product'],
            quantity_sold=ti['quantity'],
            price_at_sale=ti['price_charged'],
            cost_price=ti['cost_price'],
        )
        deduct_composite(ti['product'].id, ti['quantity'])

    if customer:
        # Only the credit leg lands on the tab — a $60 sale split $40 cash +
        # $20 credit must check and grow the balance by $20, not $60.
        if credit_amount > ZERO and not customer.is_owner and customer.credit_limit > 0:
            projected = customer.cached_balance + credit_amount
            if projected > customer.credit_limit:
                available = max(ZERO, customer.credit_limit - customer.cached_balance)
                raise ValueError(f'Store credit denied — projected balance ${projected:.2f} exceeds credit limit ${customer.credit_limit:.2f}. Only ${available:.2f} available.')
        if credit_amount > ZERO:
            customer.cached_balance += credit_amount
            customer.save(update_fields=['cached_balance'])
        # Loyalty is earned on what was actually paid in real money, so a fully
        # credit sale still scores zero (matching the pre-split rule).
        award_loyalty_points(customer_id=customer.id, amount=total - credit_amount)

    write_ledger_entry(
        session=session,
        transaction=txn,
        amount=total,
        entry_type=Ledger.EntryType.SALE,
        logged_by=operator_user or session.opened_by,
        description=f'Transaction {txn.id}',
    )

    return txn


@transaction.atomic
def void_transaction(*, txn_id, operator_user=None):
    txn = Transaction.objects.select_for_update().get(id=txn_id)

    if txn.session.status != Session.Status.OPEN:
        raise ValueError('Cannot void a transaction in a closed session.')

    if txn.status == Transaction.Status.VOIDED:
        raise ValueError('Transaction is already voided.')

    txn.status = Transaction.Status.VOIDED
    txn.save(update_fields=['status'])

    for item in txn.items.select_related('product').all():
        if item.product and not item.product.is_service:
            Product.objects.filter(id=item.product_id).update(
                stock_quantity=models.F('stock_quantity') + item.quantity_sold
            )

    credit_amount = txn.payment_amount_for(STORE_CREDIT)
    if txn.customer and credit_amount > ZERO:
        Customer.objects.filter(id=txn.customer_id).update(
            cached_balance=models.F('cached_balance') - credit_amount
        )

    Ledger.objects.create(
        session=txn.session,
        transaction=txn,
        logged_by=operator_user or txn.cashier,
        amount=-txn.total_amount,
        entry_type=Ledger.EntryType.CORRECTION,
        description=f'Void Transaction {txn.id}',
    )

    return txn


@transaction.atomic
def process_return(*, original_txn_id, return_items, refund_amount, refund_type, operator_user=None):
    original_txn = Transaction.objects.select_for_update().get(id=original_txn_id)

    if original_txn.session.status != Session.Status.POSTED:
        raise ValueError('Returns only allowed for posted sessions.')

    if original_txn.status != Transaction.Status.POSTED:
        raise ValueError('Can only return a posted transaction.')

    refund_amount = to_cents(refund_amount)
    if refund_amount <= ZERO:
        raise ValueError('Refund amount must be greater than zero.')

    if refund_type not in TENDERABLE_TYPES:
        raise ValueError(f'Invalid refund type: {refund_type}')
    if refund_type == STORE_CREDIT and not original_txn.customer:
        raise ValueError('Cannot refund to store credit without a customer on the original transaction.')

    return_txn = Transaction.objects.create(
        session=original_txn.session,
        cashier=operator_user or original_txn.cashier,
        customer=original_txn.customer,
        total_amount=-refund_amount,
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
    )

    Payment.objects.create(
        transaction=return_txn,
        payment_type=refund_type,
        amount=refund_amount,
    )

    for item in return_items:
        TransactionLineItem.objects.create(
            transaction=return_txn,
            product_id=item['product_id'],
            quantity_sold=-Decimal(str(item['quantity'])),
            price_at_sale=-Decimal(str(item.get('price_charged', 0))),
            cost_price=Decimal(str(item.get('cost_price', 0))),
        )
        Product.objects.filter(id=item['product_id'], is_service=False).update(
            stock_quantity=models.F('stock_quantity') + item['quantity']
        )

    # Keyed off the refund type, not the original sale's payment types. Before
    # the split-payment change this read the original transaction's
    # payment_type, which refunded a credit sale to cash while also cancelling
    # the tab — paying the customer out twice. Refunding over an existing credit
    # leg is allowed; it just drives cached_balance negative, which the model
    # permits.
    if original_txn.customer and refund_type == STORE_CREDIT:
        Customer.objects.filter(id=original_txn.customer_id).update(
            cached_balance=models.F('cached_balance') - refund_amount
        )

    Ledger.objects.create(
        session=original_txn.session,
        transaction=return_txn,
        logged_by=operator_user or return_txn.cashier,
        amount=-Decimal(str(refund_amount)),
        entry_type=Ledger.EntryType.CORRECTION,
        description=f'Return of Transaction {original_txn.id}',
    )

    return return_txn


@transaction.atomic
def close_session(*, session_id, actual_cash, closed_by_user):
    session = Session.objects.select_for_update().get(id=session_id, status=Session.Status.OPEN)

    # Only cash that physically reaches the drawer belongs here. Card and store
    # credit never do, and change given back out of the drawer must be netted
    # off. Each transaction's impact is signed so refunds and owner draws reduce
    # expected cash instead of adding to it.
    cash_impact = ZERO
    txns = (
        session.transactions
        .exclude(status=Transaction.Status.VOIDED)
        .exclude(total_amount=ZERO)
        .prefetch_related('payments')
    )
    for t in txns:
        cash_tendered = t.payment_amount_for(CASH)
        if cash_tendered == ZERO:
            continue
        impact = cash_tendered - t.change_due if t.total_amount > ZERO else -cash_tendered
        cash_impact += impact

    expected_cash = session.starting_cash + cash_impact

    session.closed_by = closed_by_user
    session.end_time = timezone.now()
    session.status = Session.Status.POSTED
    session.ending_cash_expected = expected_cash
    session.ending_cash_actual = Decimal(str(actual_cash))
    session.save()

    return {
        'session': session,
        'expected_cash': expected_cash,
        'actual_cash': Decimal(str(actual_cash)),
        'variance': expected_cash - Decimal(str(actual_cash)),
    }


@transaction.atomic
def process_customer_payment(*, customer_id, amount, payment_type, session_id, operator_user=None):
    session = Session.objects.select_for_update().get(id=session_id)
    customer = Customer.objects.select_for_update().get(id=customer_id)

    amount = to_cents(amount)
    if amount <= ZERO:
        raise ValueError('Payment amount must be greater than zero.')

    customer.cached_balance -= amount
    customer.save(update_fields=['cached_balance'])

    txn = Transaction.objects.create(
        session=session,
        cashier=operator_user or session.opened_by,
        customer=customer,
        total_amount=-amount,
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
    )

    Payment.objects.create(
        transaction=txn,
        payment_type=payment_type,
        amount=amount,
    )

    Ledger.objects.create(
        session=session,
        transaction=txn,
        logged_by=operator_user or session.opened_by,
        amount=-Decimal(str(amount)),
        entry_type=Ledger.EntryType.PAYMENT,
        description=f'Customer payment from {customer.name}',
    )

    return txn


@transaction.atomic
def receive_inventory(*, receipt_id, receipt_items, vendor_id, funded_by_owner, operator_user=None):
    from inventory.models import InventoryReceipt, InventoryReceiptItem

    session = Session.objects.filter(status=Session.Status.OPEN).first()
    if not session:
        raise ValueError('No active session to record inventory receipt against.')

    receipt = InventoryReceipt.objects.create(
        vendor_id=vendor_id,
        received_by=operator_user,
        funded_by_owner=funded_by_owner,
        total_cost=0,
    )

    total_cost = Decimal('0.00')
    for item in receipt_items:
        InventoryReceiptItem.objects.create(
            inventory_receipt=receipt,
            product_id=item['product_id'],
            quantity=item['quantity'],
            cost_price_at_receiving=item['cost_price'],
        )
        Product.objects.filter(id=item['product_id'], is_service=False).update(
            stock_quantity=models.F('stock_quantity') + item['quantity']
        )
        total_cost += Decimal(str(item['cost_price'])) * Decimal(str(item['quantity']))

    receipt.total_cost = total_cost
    receipt.save(update_fields=['total_cost'])

    if funded_by_owner:
        OwnerCapitalLedger.objects.create(
            owner_user_id=operator_user.id if operator_user else 0,
            amount=total_cost,
            transaction_type=OwnerCapitalLedger.TransactionType.CONTRIBUTION,
            reference_receipt_id=receipt.id,
        )

    return receipt


@transaction.atomic
def batch_offline_recovery(*, rows, operator_user=None):
    session = Session.objects.create(
        opened_by=operator_user,
        closed_by=operator_user,
        start_time=timezone.now(),
        end_time=timezone.now(),
        starting_cash=Decimal('0.00'),
        ending_cash_expected=Decimal('0.00'),
        ending_cash_actual=Decimal('0.00'),
        status=Session.Status.POSTED,
    )

    for row in rows:
        txn = Transaction.objects.create(
            session=session,
            cashier=row.get('cashier') or operator_user or session.opened_by,
            customer=row.get('customer'),
            total_amount=to_cents(row['total_amount']),
            status=Transaction.Status.POSTED,
            transaction_date=row['transaction_date'],
        )

        # Offline recovery is single-tender per row — the recovery grid has one
        # payment_type select per row, so there is no split to reconstruct.
        Payment.objects.create(
            transaction=txn,
            payment_type=row.get('payment_type') or CASH,
            amount=to_cents(row['payment_amount']),
        )

        for item in row['items']:
            TransactionLineItem.objects.create(
                transaction=txn,
                product_id=item['product_id'],
                quantity_sold=Decimal(str(item['quantity'])),
                price_at_sale=Decimal(str(item.get('price', 0))),
                cost_price=Decimal(str(item.get('cost_price', 0))),
            )
            deduct_composite(item['product_id'], Decimal(str(item['quantity'])))

        credit_amount = txn.payment_amount_for(STORE_CREDIT)
        if txn.customer and credit_amount > ZERO:
            Customer.objects.filter(id=txn.customer_id).update(
                cached_balance=models.F('cached_balance') + credit_amount
            )

    return session
