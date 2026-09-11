from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce

from customers.models import Customer
from sales.models import Transaction


class Command(BaseCommand):
    help = 'Recalculate cached_balance from STORE_CREDIT transactions only (fix for credit balance bug)'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Apply corrections to cached_balance')

    def handle(self, *args, **options):
        fix = options['fix']
        customers = Customer.objects.all()
        corrected = unchanged = 0

        for customer in customers:
            correct_balance = (
                Transaction.objects.filter(
                    customer=customer,
                    payment_type=Transaction.PaymentType.STORE_CREDIT,
                )
                .exclude(status=Transaction.Status.VOIDED)
                .aggregate(total=Coalesce(Sum('total_amount'), Value(Decimal('0.00'), output_field=DecimalField())))['total']
            )

            delta = customer.cached_balance - correct_balance

            if abs(delta) < Decimal('0.005'):
                unchanged += 1
                continue

            corrected += 1
            self.stdout.write(
                f'Customer #{customer.id} "{customer.name}" '
                f'cached_balance={customer.cached_balance} '
                f'correct={correct_balance} '
                f'delta={delta:+}'
            )

            if fix:
                customer.cached_balance = correct_balance
                customer.save(update_fields=['cached_balance'])
                self.stdout.write(f'  -> Fixed: cached_balance set to {correct_balance}')

        total = customers.count()
        self.stdout.write(f'\nChecked {total} customers: {unchanged} OK, {corrected} need correction')
        if not fix and corrected > 0:
            self.stdout.write(self.style.WARNING('Dry run — re-run with --fix to apply corrections'))
