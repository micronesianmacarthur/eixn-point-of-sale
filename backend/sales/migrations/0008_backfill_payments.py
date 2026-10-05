from decimal import Decimal

from django.db import migrations

ZERO = Decimal('0.00')


def forwards(apps, schema_editor):
    """One Payment row per existing Transaction, from its payment_type/payment_amount.

    Runs before those columns are dropped. Transactions with a zero payment
    amount (fully discounted sales, empty drafts) are skipped so receipts don't
    render a 'Cash 0.00' line for them.
    """
    Transaction = apps.get_model('sales', 'Transaction')
    Payment = apps.get_model('sales', 'Payment')

    rows = []
    for txn in Transaction.objects.all().iterator(chunk_size=500):
        amount = txn.payment_amount or ZERO
        if amount == ZERO:
            continue
        rows.append(Payment(
            transaction_id=txn.id,
            amount=amount,
            payment_type=txn.payment_type,
        ))
        if len(rows) >= 500:
            Payment.objects.bulk_create(rows)
            rows = []
    if rows:
        Payment.objects.bulk_create(rows)


def backwards(apps, schema_editor):
    """Restore the summary columns from the payment rows.

    Legacy semantics were 'first tender wins', so pick the lowest-id payment to
    stay as close to the pre-split behaviour as the data allows.
    """
    Transaction = apps.get_model('sales', 'Transaction')

    for txn in Transaction.objects.prefetch_related('payments').iterator(chunk_size=500):
        payment = txn.payments.order_by('id').first()
        if payment is None:
            continue
        txn.payment_type = payment.payment_type
        txn.payment_amount = payment.amount
        txn.save(update_fields=['payment_type', 'payment_amount'])


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0007_payment'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]