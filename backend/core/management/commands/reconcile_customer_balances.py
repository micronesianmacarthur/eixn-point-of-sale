from django.core.management.base import BaseCommand
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from customers.models import Customer
from sales.models import Transaction


class Command(BaseCommand):
    help = 'Reconcile cached_balance against actual transaction ledger entries'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Update cached_balance to match ledger')

    def handle(self, *args, **options):
        fix = options['fix']
        customers = Customer.objects.all()
        reconciled = errors = 0

        for customer in customers:
            expected = (
                Transaction.objects.filter(customer=customer)
                .exclude(status=Transaction.Status.VOIDED)
                .aggregate(total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())))['total']
            )
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
