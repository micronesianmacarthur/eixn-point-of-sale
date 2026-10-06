from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounting.models import OwnerCapitalLedger
from core.models import BusinessInfo
from customers.models import Customer
from inventory.models import (
    InventoryAdjustment,
    InventoryReceipt,
    InventoryReceiptItem,
    InventoryStockCount,
    Product,
    Vendor,
)
from sales.models import Session, Transaction
from users.models import User

from .services import post_stock_count, receive_inventory


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
        self.assertEqual(txn.payment_amount_for('OWNER_DRAW'), Decimal('25.00'))
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


class StockCountReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        BusinessInfo.objects.create(business_name='Test Biz')
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.product = Product.objects.create(
            vendor=cls.vendor, name='Sourdough Bread', sku='BAK-012',
            cost_price=Decimal('2.50'), retail_price=Decimal('5.99'),
            stock_quantity=Decimal('50'), min_stock_level=Decimal('10'),
        )
        cls.service = Product.objects.create(
            vendor=cls.vendor, name='Consulting', sku='SRV-001',
            cost_price=Decimal('0'), retail_price=Decimal('100'),
            stock_quantity=Decimal('1'), is_service=True,
        )
        cls.cashier = User.objects.create_user(
            username='cashier', password='pass', role=User.Role.CASHIER,
        )
        cls.manager = User.objects.create_user(
            username='manager', password='pass', role=User.Role.MANAGER,
        )

    def test_report_lists_stockable_products_only(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse('inventory:inventory_report'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.product.sku)
        self.assertNotContains(resp, self.service.sku)

    def test_report_cost_valuation(self):
        self.client.force_login(self.manager)
        resp = self.client.get(reverse('inventory:inventory_report'), {'price': 'cost'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '125.00')  # 50 x 2.50

    def test_count_pages_manager_only(self):
        for url in (
            reverse('inventory:count_entry'),
            reverse('inventory:count_post'),
            reverse('inventory:adjustment_list'),
        ):
            self.client.force_login(self.cashier)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403)


class PostStockCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        BusinessInfo.objects.create(business_name='Test Biz')
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.manager = User.objects.create_user(
            username='manager', password='pass', role=User.Role.MANAGER,
        )

    def setUp(self):
        self.p1 = Product.objects.create(
            vendor=self.vendor, name='Bread', sku='BAK-001',
            cost_price=Decimal('2.00'), retail_price=Decimal('5.00'),
            stock_quantity=Decimal('50'),
        )
        self.p2 = Product.objects.create(
            vendor=self.vendor, name='Water', sku='BVR-001',
            cost_price=Decimal('1.00'), retail_price=Decimal('2.00'),
            stock_quantity=Decimal('20'),
        )

    def assert_stock(self, product, qty):
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, qty)

    def test_posts_changes_and_writes_adjustments(self):
        count, adjustments = post_stock_count(
            items=[
                {'product_id': self.p1.id, 'counted_qty': Decimal('48'), 'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT},
                {'product_id': self.p2.id, 'counted_qty': Decimal('50'), 'reason': InventoryAdjustment.Reason.FOUND},
            ],
            adjusted_by=self.manager,
            note='Sept count',
        )

        self.assertIsNotNone(count)
        self.assertEqual(count.status, InventoryStockCount.Status.POSTED)
        self.assertEqual(count.note, 'Sept count')
        self.assertEqual(count.created_by, self.manager)
        self.assertIsNotNone(count.posted_at)

        self.assertEqual(InventoryAdjustment.objects.count(), 2)
        adj1 = InventoryAdjustment.objects.get(product=self.p1)
        self.assertEqual(adj1.previous_qty, Decimal('50'))
        self.assertEqual(adj1.adjusted_qty, Decimal('48'))
        self.assertEqual(adj1.delta, Decimal('-2'))
        self.assertEqual(adj1.delta_cost_value, Decimal('-4.00'))
        self.assertEqual(adj1.reason, InventoryAdjustment.Reason.PHYSICAL_COUNT)
        self.assertEqual(adj1.adjusted_by, self.manager)
        self.assertEqual(adj1.stock_count, count)

        adj2 = InventoryAdjustment.objects.get(product=self.p2)
        self.assertEqual(adj2.delta, Decimal('30'))
        self.assertEqual(adj2.delta_cost_value, Decimal('30.00'))

        self.assert_stock(self.p1, Decimal('48'))
        self.assert_stock(self.p2, Decimal('50'))

    def test_matching_counts_skip_and_clean(self):
        count, adjustments = post_stock_count(
            items=[
                {'product_id': self.p1.id, 'counted_qty': Decimal('50'), 'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT},
                {'product_id': self.p2.id, 'counted_qty': Decimal('20'), 'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT},
            ],
            adjusted_by=self.manager,
        )
        self.assertIsNone(count)
        self.assertEqual(adjustments, [])
        self.assertEqual(InventoryStockCount.objects.count(), 0)
        self.assertEqual(InventoryAdjustment.objects.count(), 0)

    def test_negative_count_rejected(self):
        with self.assertRaises(ValueError):
            post_stock_count(
                items=[{'product_id': self.p1.id, 'counted_qty': Decimal('-1'), 'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT}],
                adjusted_by=self.manager,
            )
        self.assert_stock(self.p1, Decimal('50'))
        self.assertEqual(InventoryStockCount.objects.count(), 0)
        self.assertEqual(InventoryAdjustment.objects.count(), 0)

    def test_empty_items_rejected(self):
        with self.assertRaises(ValueError):
            post_stock_count(items=[], adjusted_by=self.manager)

    def test_post_view_updates_stock_and_redirects(self):
        self.client.force_login(self.manager)
        resp = self.client.post(reverse('inventory:count_post'), {
            'product_id': [str(self.p1.id), str(self.p2.id)],
            f'qty_{self.p1.id}': '48',
            f'qty_{self.p2.id}': '50',
            f'reason_{self.p1.id}': InventoryAdjustment.Reason.PHYSICAL_COUNT,
            f'reason_{self.p2.id}': InventoryAdjustment.Reason.FOUND,
            'note': 'Sept count',
        })
        self.assertEqual(resp.status_code, 302)
        self.assert_stock(self.p1, Decimal('48'))
        self.assert_stock(self.p2, Decimal('50'))
        count = InventoryStockCount.objects.get()
        self.assertEqual(InventoryAdjustment.objects.count(), 2)


class ProductArchiveTests(TestCase):
    """`is_active=False` must hide a product from every interactive screen while
    leaving the row (and its history) intact."""

    @classmethod
    def setUpTestData(cls):
        BusinessInfo.objects.create(business_name='Test Biz')
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.manager = User.objects.create_user(
            username='manager', password='pass', role=User.Role.MANAGER,
        )
        cls.cashier = User.objects.create_user(
            username='cashier', password='pass', role=User.Role.CASHIER,
        )

    def setUp(self):
        self.live = Product.objects.create(
            vendor=self.vendor, name='Live Bread', sku='BAK-100',
            cost_price=Decimal('2.00'), retail_price=Decimal('5.00'),
            stock_quantity=Decimal('10'), min_stock_level=Decimal('4'),
        )
        self.gone = Product.objects.create(
            vendor=self.vendor, name='Discontinued Loaf', sku='BAK-999',
            cost_price=Decimal('3.00'), retail_price=Decimal('6.00'),
            stock_quantity=Decimal('7'), min_stock_level=Decimal('4'),
        )
        self.client.force_login(self.manager)

    def archive(self):
        # Note: the success message names the product and is rendered on the next
        # page load, so "must not appear" assertions below match on SKU instead.
        return self.client.post(reverse('inventory:product_delete', args=[self.gone.id]))

    # --- queryset ---------------------------------------------------------

    def test_queryset_partitions_active_and_archived(self):
        self.gone.is_active = False
        self.gone.save(update_fields=['is_active'])
        self.assertEqual(
            list(Product.objects.active().values_list('id', flat=True)),
            [self.live.id],
        )
        self.assertEqual(
            list(Product.objects.archived().values_list('id', flat=True)),
            [self.gone.id],
        )
        # The default manager stays unfiltered so reports and history keep working.
        self.assertEqual(Product.objects.count(), 2)

    # --- archiving instead of deleting -----------------------------------

    def test_delete_archives_and_keeps_row(self):
        resp = self.archive()
        self.assertEqual(resp.status_code, 302)
        self.gone.refresh_from_db()
        self.assertFalse(self.gone.is_active)
        self.assertEqual(Product.objects.count(), 2)

    def test_archive_succeeds_even_when_history_references_the_product(self):
        # A receipt alone is enough to make a hard delete impossible (PROTECT).
        receipt = receive_inventory(
            vendor=self.vendor,
            received_by=self.manager,
            items=[{'product_id': self.gone.id, 'quantity': Decimal('7'), 'cost_price': Decimal('3.00')}],
        )
        self.assertIsNotNone(receipt)
        self.archive()
        self.gone.refresh_from_db()
        self.assertFalse(self.gone.is_active)
        self.assertEqual(InventoryReceiptItem.objects.filter(product=self.gone).count(), 1)

    def test_archiving_twice_is_a_no_op(self):
        self.archive()
        self.archive()
        self.gone.refresh_from_db()
        self.assertFalse(self.gone.is_active)
        self.assertEqual(Product.objects.count(), 2)

    def test_delete_requires_manager(self):
        self.client.force_login(self.cashier)
        self.archive()
        self.gone.refresh_from_db()
        self.assertTrue(self.gone.is_active)

    def test_update_restores_an_archived_product(self):
        self.archive()
        resp = self.client.post(reverse('inventory:product_update', args=[self.gone.id]), {
            'name': self.gone.name,
            'vendor': self.vendor.id,
            'retail_price': '6.50',
            'min_stock_level': '0',
            'is_active': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.gone.refresh_from_db()
        self.assertTrue(self.gone.is_active)

    # --- interactive screens hide archived products -----------------------

    def test_product_list_hides_archived_until_asked(self):
        self.archive()
        resp = self.client.get(reverse('inventory:product_list'))
        self.assertContains(resp, self.live.sku)
        self.assertNotContains(resp, self.gone.sku)

        resp = self.client.get(reverse('inventory:product_list'), {'archived': '1'})
        self.assertContains(resp, self.gone.sku)
        self.assertContains(resp, 'Archived')

    def test_product_table_partial_hides_archived(self):
        self.archive()
        resp = self.client.get(reverse('inventory:product_table'))
        self.assertNotContains(resp, self.gone.sku)
        resp = self.client.get(reverse('inventory:product_table'), {'archived': '1'})
        self.assertContains(resp, self.gone.sku)

    def test_count_entry_offers_only_live_products(self):
        self.archive()
        resp = self.client.get(reverse('inventory:count_entry'))
        self.assertContains(resp, self.live.sku)
        self.assertNotContains(resp, self.gone.sku)

    def test_receive_screen_offers_only_live_products(self):
        self.archive()
        resp = self.client.get(reverse('inventory:receive_products'))
        self.assertNotContains(resp, self.gone.sku)

    def test_repack_search_hides_archived(self):
        self.archive()
        resp = self.client.get(reverse('inventory:repack_product_search'), {'q': 'Loaf'})
        self.assertNotContains(resp, self.gone.sku)

    # --- reports and history keep archived products -----------------------

    def test_inventory_report_still_values_archived_stock(self):
        self.archive()
        resp = self.client.get(reverse('inventory:inventory_report'), {'price': 'cost'})
        self.assertContains(resp, self.gone.sku)
        # 10 x 2.00 + 7 x 3.00 = 41.00
        self.assertContains(resp, '41.00')

    def test_product_detail_still_reachable(self):
        self.archive()
        resp = self.client.get(reverse('inventory:product_detail', args=[self.gone.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'is archived')

    # --- stock-writing paths reject archived products ---------------------

    def test_stock_count_rejects_archived_product(self):
        self.archive()
        resp = self.client.post(reverse('inventory:count_post'), {
            'product_id': [str(self.gone.id)],
            f'qty_{self.gone.id}': '3',
            f'reason_{self.gone.id}': InventoryAdjustment.Reason.PHYSICAL_COUNT,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('inventory:count_entry'), resp.url)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('7'))
        self.assertEqual(InventoryAdjustment.objects.count(), 0)

    def test_post_stock_count_rejects_archived_product(self):
        self.archive()
        with self.assertRaises(ValueError):
            post_stock_count(
                items=[{'product_id': self.gone.id, 'counted_qty': Decimal('3'),
                        'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT}],
                adjusted_by=self.manager,
            )
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('7'))

    def test_receive_inventory_rejects_archived_product(self):
        self.archive()
        with self.assertRaises(ValueError):
            receive_inventory(
                vendor=self.vendor,
                received_by=self.manager,
                items=[{'product_id': self.gone.id, 'quantity': Decimal('5'),
                        'cost_price': Decimal('3.00')}],
            )
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('7'))
        self.assertEqual(InventoryReceipt.objects.count(), 0)

    def test_receive_view_rejects_archived_product_id(self):
        self.archive()
        Session.objects.create(opened_by=self.manager, starting_cash=Decimal('0.00'))
        resp = self.client.post(reverse('inventory:receive_products'), {
            'vendor': self.vendor.id,
            'product_1': str(self.gone.id),
            'qty_1': '5',
            'cost_price_1': '3.00',
            'retail_price_1': '6.00',
        })
        self.assertEqual(resp.status_code, 200)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('7'))
        self.assertEqual(InventoryReceipt.objects.count(), 0)

    def test_repack_rejects_archived_parent(self):
        self.archive()
        resp = self.client.post(reverse('inventory:repack'), {
            'action': 'execute',
            'parent_id': str(self.gone.id),
            'parent_qty': '1',
        })
        self.assertEqual(resp.status_code, 302)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('7'))
