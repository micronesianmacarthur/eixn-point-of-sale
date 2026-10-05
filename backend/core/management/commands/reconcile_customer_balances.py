from django.core.management.base import BaseCommand
from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from customers.models import Customer
from sales.models import Payment, Transaction
from sales.services import to_cents

# VOIDED transactions must not contribute; everything else (POSTED, DRAFT) does.
ACTIVE_STATUSES = [s for s in Transaction.Status.values if s != Transaction.Status.VOIDED]


class Command(BaseCommand):
    help = 'Reconcile cached_balance against actual transaction ledger entries'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Update cached_balance to match ledger')

    def handle(self, *args, **options):
        fix = options['fix']
        customers = Customer.objects.all()
        reconciled = errors = 0

        for customer in customers:
            # Expected balance is the store credit actually tendered, signed by
            # the transaction's direction: a credit sale adds its credit leg to
            # the tab, a refund paid back onto the tab subtracts it. Summing
            # whole transaction totals (the pre-split approach) cannot express a
            # sale that was split cash + credit.
            expected = (
                Payment.objects.filter(
                    transaction__customer=customer,
                    transaction__status__in=ACTIVE_STATUSES,
                    payment_type=Payment.PaymentType.STORE_CREDIT,
                )
                .select_related('transaction')
                .annotate(
                    signed=Case(
                        When(transaction__total_amount__lt=0, then=-F('amount')),
                        default=F('amount'),
                        output_field=DecimalField(),
                    )
                )
                .aggregate(total=Coalesce(Sum('signed'), Value(0, output_field=DecimalField())))['total']
            )
            expected = to_cents(expected)
            delta = customer.cached_balance - expected

            if delta == 0:
                reconciled += 1
                continue

            errors += 1
            level = 'WARNING'
            if abs(delta) > 1000:
                level = 'ERROR'
            self.stdout.write(
                f'{level}: Customer #{customer.id} "{customer.name}" '
                f'cached_balance={customer.cached_balance} '
                f'expected={expected} '
                f'delta={delta}'
            )

            if fix and abs(delta) > 0.005:
                customer.cached_balance = expected
                customer.save(update_fields=['cached_balance'])
                self.stdout.write(f'  -> Fixed: cached_balance set to {expected}')

        total = customers.count()
        self.stdout.write(f'\nChecked {total} customers: {reconciled} OK, {errors} discrepancies')
