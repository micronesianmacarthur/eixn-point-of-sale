from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from sales.models import Session, Transaction
from users.models import User

from .models import Ledger, OwnerCapitalLedger
from .services import process_owner_contribution


class ProcessOwnerContributionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN
        )
        cls.operator = User.objects.create_user(
            username='cashier', password='pass', role=User.Role.CASHIER
        )
        cls.owner = Customer.objects.create(
            name='Owner User', is_owner=True, cached_balance=Decimal('100.00'),
            credit_limit=Decimal('500.00'),
        )
        cls.non_owner = Customer.objects.create(
            name='Regular Customer', is_owner=False, cached_balance=Decimal('50.00'),
            credit_limit=Decimal('200.00'),
        )
        cls.session = Session.objects.create(
            opened_by=cls.admin, starting_cash=Decimal('100.00'),
        )

    def test_zero_contribution_returns_none(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('0'),
        )
        self.assertIsNone(result)
        self.assertEqual(
            OwnerCapitalLedger.objects.count(), 0,
        )
        self.assertEqual(Transaction.objects.count(), 0)

    def test_negative_contribution_returns_none(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('-10'),
        )
        self.assertIsNone(result)

    def test_non_owner_returns_none(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.non_owner,
            operator_user=self.operator, contribution_amount=Decimal('50'),
        )
        self.assertIsNone(result)

    def test_contribution_less_than_balance(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('30'),
        )
        self.assertEqual(result, Decimal('30'))

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.cached_balance, Decimal('70.00'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 2)
        contrib = OwnerCapitalLedger.objects.get(transaction_type='CONTRIBUTION')
        self.assertEqual(contrib.amount, Decimal('30'))
        self.assertEqual(contrib.owner_user_id, self.owner.id)

        draw = OwnerCapitalLedger.objects.get(transaction_type='DRAW')
        self.assertEqual(draw.amount, Decimal('30'))

        self.assertEqual(Transaction.objects.count(), 1)
        txn = Transaction.objects.first()
        self.assertEqual(txn.total_amount, Decimal('-30'))
        self.assertEqual(txn.payment_type, Transaction.PaymentType.OWNER_DRAW)
        self.assertEqual(txn.customer, self.owner)
        self.assertEqual(txn.cashier, self.operator)
        self.assertEqual(txn.session, self.session)

    def test_contribution_equal_to_balance(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('100'),
        )
        self.assertEqual(result, Decimal('100'))

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.cached_balance, Decimal('0.00'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 2)
        self.assertEqual(Transaction.objects.count(), 1)
        txn = Transaction.objects.first()
        self.assertEqual(txn.total_amount, Decimal('-100'))

    def test_contribution_more_than_balance_draws_only_balance(self):
        result = process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('250'),
        )
        self.assertEqual(result, Decimal('100'))

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.cached_balance, Decimal('0.00'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 2)
        contrib = OwnerCapitalLedger.objects.get(transaction_type='CONTRIBUTION')
        self.assertEqual(contrib.amount, Decimal('250'))

        draw = OwnerCapitalLedger.objects.get(transaction_type='DRAW')
        self.assertEqual(draw.amount, Decimal('100'))

        self.assertEqual(Transaction.objects.count(), 1)
        txn = Transaction.objects.first()
        self.assertEqual(txn.total_amount, Decimal('-100'))

    def test_balance_zero_no_draw_created(self):
        owner_zero = Customer.objects.create(
            name='Zero Balance Owner', is_owner=True, cached_balance=Decimal('0.00'),
        )
        result = process_owner_contribution(
            session=self.session, owner_customer=owner_zero,
            operator_user=self.operator, contribution_amount=Decimal('50'),
        )
        self.assertEqual(result, Decimal('0'))

        owner_zero.refresh_from_db()
        self.assertEqual(owner_zero.cached_balance, Decimal('0.00'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 1)
        self.assertEqual(
            OwnerCapitalLedger.objects.filter(transaction_type='CONTRIBUTION').count(), 1,
        )
        self.assertEqual(
            OwnerCapitalLedger.objects.filter(transaction_type='DRAW').count(), 0,
        )
        self.assertEqual(Transaction.objects.count(), 0)

    def test_multiple_contributions_accumulate(self):
        process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('30'),
        )
        process_owner_contribution(
            session=self.session, owner_customer=self.owner,
            operator_user=self.operator, contribution_amount=Decimal('20'),
        )

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.cached_balance, Decimal('50.00'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 4)
        self.assertEqual(Transaction.objects.count(), 2)
