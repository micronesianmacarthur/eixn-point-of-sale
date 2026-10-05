from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import BusinessInfo
from inventory.models import Category, Product, Vendor
from users.models import User

from .models import Session
from .services import process_checkout, void_transaction


class DashboardVoidExclusionTests(TestCase):
    """Voided transactions must not inflate any figure on the dashboard.

    Regression tests for the "today" revenue card, which aggregated every
    transaction regardless of status while the monthly card, the 30-day chart,
    the by-clerk table and the weekly comparison all excluded voided sales.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN
        )
        BusinessInfo.objects.create(business_name='Test Shop')
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.category = Category.objects.create(name='General')
        cls.product = Product.objects.create(
            name='Widget', category=cls.category, vendor=cls.vendor, sku='W-1',
            retail_price=Decimal('10.00'), cost_price=Decimal('4.00'),
            stock_quantity=Decimal('1000'),
        )

    def setUp(self):
        self.session = Session.objects.create(
            opened_by=self.admin, starting_cash=Decimal('0.00'),
        )
        # Noon local keeps the calendar date unambiguous on both sides of the
        # __date lookup, whatever the host timezone is.
        self.today_noon = timezone.localtime(timezone.now()).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )

    def sell(self, quantity, *, transaction_date=None):
        amount = Decimal('10.00') * quantity
        txn = process_checkout(
            session_id=self.session.id,
            items=[{'product_id': self.product.id, 'quantity': quantity}],
            payments=[{'payment_type': 'CASH', 'amount': str(amount)}],
            operator_user=self.admin,
        )
        if transaction_date is not None:
            txn.transaction_date = transaction_date
            txn.save(update_fields=['transaction_date'])
        return txn

    def dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('sales:dashboard'))
        self.assertEqual(response.status_code, 200)
        return response.context_data

    def test_revenue_ignores_voided_transactions(self):
        self.sell(10, transaction_date=self.today_noon)          # $100.00
        voided = self.sell(5, transaction_date=self.today_noon)   # $50.00, voided
        void_transaction(txn_id=voided.id, operator_user=self.admin)

        context = self.dashboard()

        self.assertEqual(context['sales_today_total'], Decimal('100.00'))

    def test_transaction_count_ignores_voided_transactions(self):
        self.sell(10, transaction_date=self.today_noon)
        voided = self.sell(5, transaction_date=self.today_noon)
        void_transaction(txn_id=voided.id, operator_user=self.admin)

        context = self.dashboard()

        self.assertEqual(context['sales_today_count'], 1)

    def test_top_product_ignores_voided_line_items(self):
        self.sell(10, transaction_date=self.today_noon)
        voided = self.sell(5, transaction_date=self.today_noon)
        void_transaction(txn_id=voided.id, operator_user=self.admin)

        context = self.dashboard()

        self.assertEqual(context['top_product']['total_qty'], Decimal('10.000'))

    def test_all_voided_today_reports_zero_rather_than_crashing(self):
        voided = self.sell(5, transaction_date=self.today_noon)
        void_transaction(txn_id=voided.id, operator_user=self.admin)

        context = self.dashboard()

        self.assertEqual(context['sales_today_total'], 0)
        self.assertEqual(context['sales_today_count'], 0)
        self.assertIsNone(context['top_product'])

    def test_posted_transactions_are_still_counted(self):
        """Guards against over-filtering, e.g. dropping every transaction."""
        self.sell(10, transaction_date=self.today_noon)
        self.sell(5, transaction_date=self.today_noon)

        context = self.dashboard()

        self.assertEqual(context['sales_today_total'], Decimal('150.00'))
        self.assertEqual(context['sales_today_count'], 2)
        self.assertEqual(context['top_product']['total_qty'], Decimal('15.000'))

    def test_other_days_untouched_by_the_void(self):
        self.sell(10, transaction_date=self.today_noon)
        yesterday = self.sell(5, transaction_date=self.today_noon - timedelta(days=1))
        void_transaction(txn_id=yesterday.id, operator_user=self.admin)

        context = self.dashboard()

        # Voiding a sale from another day must not disturb today's figures.
        self.assertEqual(context['sales_today_total'], Decimal('100.00'))
        self.assertEqual(context['sales_today_count'], 1)