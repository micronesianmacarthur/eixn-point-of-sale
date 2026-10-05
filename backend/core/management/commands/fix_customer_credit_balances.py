from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

from customers.models import Customer
from sales.models import Payment, Transaction
from sales.services import to_cents

# VOIDED transactions must not contribute; everything else (POSTED, DRAFT) does.
ACTIVE_STATUSES = [s for s in Transaction.Status.values if s != Transaction.Status.VOIDED]


class Command(BaseCommand):
    help = 'Recalculate cached_balance from STORE_CREDIT payment legs only (fix for credit balance bug)'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Apply corrections to cached_balance')

    def handle(self, *args, **options):
        fix = options['fix']
        customers = Customer.objects.all()
        corrected = unchanged = 0

        for customer in customers:
            # Sum the STORE_CREDIT payment legs, signed by transaction
            # direction: credit sales grow the tab, refunds paid onto the tab
            # shrink it. Sums the whole transaction total instead, this cannot
            # account for a sale split cash + credit.
            correct_balance = to_cents(
                Payment.objects.filter(
                    transaction__customer=customer,
                    transaction__status__in=ACTIVE_STATUSES,
                    payment_type=Payment.PaymentType.STORE_CREDIT,
                )
                .annotate(
                    signed=Case(
                        When(transaction__total_amount__lt=0, then=-F('amount')),
                        default=F('amount'),
                        output_field=DecimalField(),
                    )
                )
                .aggregate(
                    total=Coalesce(Sum('signed'), Value(Decimal('0.00'), output_field=DecimalField()))
                )['total']
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
