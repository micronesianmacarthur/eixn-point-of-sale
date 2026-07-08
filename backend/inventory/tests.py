from decimal import Decimal

from django.test import TestCase

from accounting.models import OwnerCapitalLedger
from customers.models import Customer
from inventory.models import InventoryReceipt, InventoryReceiptItem, Product, Vendor
from sales.models import Session, Transaction
from users.models import User

from .services import receive_inventory


class ReceiveInventoryWithOwnerContributionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN,
        )
        cls.operator = User.objects.create_user(
            username='cashier', password='pass', role=User.Role.CASHIER,
        )
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.product = Product.objects.create(
            vendor=cls.vendor, name='Test Product', sku='TST-001',
            cost_price=Decimal('5.00'), retail_price=Decimal('10.00'),
            stock_quantity=Decimal('10'),
        )
        cls.owner = Customer.objects.create(
            name='Owner User', is_owner=True, cached_balance=Decimal('100.00'),
        )
        cls.non_owner = Customer.objects.create(
            name='Regular Customer', is_owner=False, cached_balance=Decimal('50.00'),
            credit_limit=Decimal('200.00'),
        )
        cls.session = Session.objects.create(
            opened_by=cls.admin, starting_cash=Decimal('100.00'),
        )

    def test_receive_inventory_with_owner_contribution(self):
        receipt = receive_inventory(
            vendor=self.vendor,
            received_by=self.operator,
            items=[{
                'product_id': self.product.id,
                'quantity': 5,
                'cost_price': Decimal('5.00'),
            }],
            funded_by_owner=True,
            owner_contribution_amount=Decimal('25.00'),
            owner_customer_id=self.owner.id,
            session=self.session,
            operator_user=self.operator,
        )

        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.total_cost, Decimal('25.00'))
        self.assertTrue(receipt.funded_by_owner)
        self.assertEqual(receipt.owner_customer, self.owner)

        self.assertEqual(InventoryReceiptItem.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('15'))

        self.assertEqual(OwnerCapitalLedger.objects.count(), 2)
        contrib = OwnerCapitalLedger.objects.get(transaction_type='CONTRIBUTION')
        self.assertEqual(contrib.amount, Decimal('25.00'))
        draw = OwnerCapitalLedger.objects.get(transaction_type='DRAW')
        self.assertEqual(draw.amount, Decimal('25.00'))

        self.assertEqual(Transaction.objects.count(), 1)
        txn = Transaction.objects.first()
        self.assertEqual(txn.total_amount, Decimal('-25.00'))
        self.assertEqual(txn.payment_type, Transaction.PaymentType.OWNER_DRAW)
        self.assertEqual(txn.customer, self.owner)

        self.owner.refresh_from_db()
        self.assertEqual(self.owner.cached_balance, Decimal('75.00'))

    def test_receive_inventory_without_owner_contribution(self):
        receipt = receive_inventory(
            vendor=self.vendor,
            received_by=self.operator,
            items=[{
                'product_id': self.product.id,
                'quantity': 3,
                'cost_price': Decimal('5.00'),
            }],
            session=self.session,
            operator_user=self.operator,
        )

        self.assertIsNotNone(receipt)
        self.assertFalse(receipt.funded_by_owner)
        self.assertIsNone(receipt.owner_customer)

        self.assertEqual(OwnerCapitalLedger.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('13'))

    def test_receive_inventory_no_session_no_contribution(self):
        receipt = receive_inventory(
            vendor=self.vendor,
            received_by=self.operator,
            items=[{
                'product_id': self.product.id,
                'quantity': 2,
                'cost_price': Decimal('5.00'),
            }],
            funded_by_owner=True,
            owner_contribution_amount=Decimal('10.00'),
            owner_customer_id=self.owner.id,
            operator_user=self.operator,
        )

        self.assertIsNotNone(receipt)
        self.assertEqual(OwnerCapitalLedger.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_receive_inventory_owner_contribution_draws_less_than_full(self):
        low_balance_owner = Customer.objects.create(
            name='Low Bal Owner', is_owner=True, cached_balance=Decimal('10.00'),
        )
        receipt = receive_inventory(
            vendor=self.vendor,
            received_by=self.operator,
            items=[{
                'product_id': self.product.id,
                'quantity': 10,
                'cost_price': Decimal('5.00'),
            }],
            funded_by_owner=True,
            owner_contribution_amount=Decimal('50.00'),
            owner_customer_id=low_balance_owner.id,
            session=self.session,
            operator_user=self.operator,
        )

        self.assertEqual(OwnerCapitalLedger.objects.count(), 2)
        contrib = OwnerCapitalLedger.objects.get(transaction_type='CONTRIBUTION')
        self.assertEqual(contrib.amount, Decimal('50.00'))
        draw = OwnerCapitalLedger.objects.get(transaction_type='DRAW')
        self.assertEqual(draw.amount, Decimal('10.00'))

        low_balance_owner.refresh_from_db()
        self.assertEqual(low_balance_owner.cached_balance, Decimal('0.00'))
