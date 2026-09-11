from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from accounting.models import Ledger, OwnerCapitalLedger
from accounting.services import write_ledger_entry
from customers.models import Customer
from customers.services import award_loyalty_points
from inventory.models import Product
from inventory.services import deduct_composite

from .models import Session, Transaction, TransactionLineItem


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
        line_total = price * qty
        total += line_total

        if not product.is_service and product.stock_quantity < qty:
            raise ValueError(f'Insufficient stock for {product.name}')

        txn_items.append({
            'product': product,
            'quantity': qty,
            'cost_price': product.cost_price,
            'price_charged': price,
        })

    payment_type = payments[0]['payment_type'] if payments else 'CASH'
    payment_amount = Decimal(str(payments[0]['amount'])) if payments else total

    txn = Transaction.objects.create(
        session=session,
        cashier=operator_user or session.opened_by,
        customer=customer,
        total_amount=total,
        payment_type=payment_type,
        payment_amount=payment_amount,
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
    )

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
        if payment_type == Transaction.PaymentType.STORE_CREDIT and not customer.is_owner and customer.credit_limit > 0:
            projected = customer.cached_balance + total
            if projected > customer.credit_limit:
                available = max(Decimal('0.00'), customer.credit_limit - customer.cached_balance)
                raise ValueError(f'Store credit denied — projected balance ${projected:.2f} exceeds credit limit ${customer.credit_limit:.2f}. Only ${available:.2f} available.')
        if payment_type == Transaction.PaymentType.STORE_CREDIT:
            customer.cached_balance += total
            customer.save(update_fields=['cached_balance'])
        award_loyalty_points(customer_id=customer.id, total=total, payment_type=payment_type)

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

    if txn.customer and txn.payment_type == Transaction.PaymentType.STORE_CREDIT:
        Customer.objects.filter(id=txn.customer_id).update(
            cached_balance=models.F('cached_balance') - txn.total_amount
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

    return_txn = Transaction.objects.create(
        session=original_txn.session,
        cashier=operator_user or original_txn.cashier,
        customer=original_txn.customer,
        total_amount=-Decimal(str(refund_amount)),
        payment_type=refund_type,
        payment_amount=Decimal(str(refund_amount)),
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
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

    if original_txn.customer and original_txn.payment_type == Transaction.PaymentType.STORE_CREDIT:
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

    total_revenue = sum(
        (t.total_amount for t in session.transactions.exclude(status=Transaction.Status.VOIDED)),
        session.starting_cash.__class__(0)
    )
    expected_cash = session.starting_cash + total_revenue

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

    customer.cached_balance -= Decimal(str(amount))
    customer.save(update_fields=['cached_balance'])

    txn = Transaction.objects.create(
        session=session,
        cashier=operator_user or session.opened_by,
        customer=customer,
        total_amount=-Decimal(str(amount)),
        payment_type=payment_type,
        payment_amount=Decimal(str(amount)),
        status=Transaction.Status.POSTED,
        transaction_date=timezone.now(),
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
            total_amount=Decimal(str(row['total_amount'])),
            payment_type=row.get('payment_type', Transaction.PaymentType.CASH),
            payment_amount=Decimal(str(row['payment_amount'])),
            status=Transaction.Status.POSTED,
            transaction_date=row['transaction_date'],
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

        if txn.customer and txn.payment_type == Transaction.PaymentType.STORE_CREDIT:
            Customer.objects.filter(id=txn.customer_id).update(
                cached_balance=models.F('cached_balance') + txn.total_amount
            )

    return session
