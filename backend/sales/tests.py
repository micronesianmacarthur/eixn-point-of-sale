import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounting.models import Ledger
from core.models import BusinessInfo
from customers.models import Customer
from inventory.models import Bundle, BundleItem, Category, Product, Vendor
from users.models import User

from .models import Payment, Session, Transaction
from .services import close_session, process_checkout, process_return, void_transaction


class CheckoutBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN
        )
        cls.vendor = Vendor.objects.create(name='Test Vendor')
        cls.category = Category.objects.create(name='General')
        cls.product = Product.objects.create(
            name='Widget', category=cls.category, vendor=cls.vendor, sku='W-1',
            retail_price=Decimal('10.00'), cost_price=Decimal('4.00'),
            stock_quantity=Decimal('100'),
        )
        cls.customer = Customer.objects.create(
            name='Credit Customer', credit_limit=Decimal('500.00'),
            cached_balance=Decimal('0.00'),
        )

    def setUp(self):
        self.session = Session.objects.create(
            opened_by=self.admin, starting_cash=Decimal('0.00'),
        )

    def checkout(self, *, payments, items=None, customer=None):
        return process_checkout(
            session_id=self.session.id,
            items=items or [{'product_id': self.product.id, 'quantity': 1}],
            payments=payments,
            customer_id=customer.id if customer else None,
            operator_user=self.admin,
        )

    def cash(self, amount):
        return {'payment_type': Payment.PaymentType.CASH, 'amount': amount}

    def card(self, amount):
        return {'payment_type': Payment.PaymentType.CARD, 'amount': amount}

    def credit(self, amount):
        return {'payment_type': Payment.PaymentType.ACCOUNT, 'amount': amount}


class SinglePaymentTests(CheckoutBase):
    def test_single_cash_payment_creates_one_payment_row(self):
        txn = self.checkout(payments=[self.cash('10.00')])

        self.assertEqual(txn.total_amount, Decimal('10.00'))
        self.assertEqual(txn.payments.count(), 1)
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('10.00'))
        self.assertEqual(txn.change_due, Decimal('0.00'))

    def test_exact_card_payment_has_no_change(self):
        txn = self.checkout(payments=[self.card('10.00')])
        self.assertEqual(txn.change_due, Decimal('0.00'))

    def test_cash_over_tender_records_change(self):
        txn = self.checkout(payments=[self.cash('20.00')])
        self.assertEqual(txn.change_due, Decimal('10.00'))

    def test_no_payments_list_defaults_to_full_cash(self):
        txn = self.checkout(payments=[])
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('10.00'))


class SplitPaymentTests(CheckoutBase):
    def test_cash_plus_card_split(self):
        txn = self.checkout(payments=[self.cash('4.00'), self.card('6.00')])

        self.assertEqual(txn.total_amount, Decimal('10.00'))
        self.assertEqual(txn.payments.count(), 2)
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('4.00'))
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CARD), Decimal('6.00'))
        self.assertEqual(txn.change_due, Decimal('0.00'))

    def test_three_way_split(self):
        txn = self.checkout(
            payments=[self.cash('3.00'), self.card('2.00'), self.credit('5.00')],
            customer=self.customer,
        )

        self.assertEqual(txn.payments.count(), 3)
        self.assertEqual(txn.change_due, Decimal('0.00'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('5.00'))

    def test_cash_overshoot_across_split_gives_change(self):
        # Card first, then cash past the balance: only the cash leg can overshoot.
        txn = self.checkout(payments=[self.card('4.00'), self.cash('8.00')])

        self.assertEqual(txn.total_amount, Decimal('10.00'))
        self.assertEqual(txn.change_due, Decimal('2.00'))

    def test_repeated_type_merges_into_one_row(self):
        txn = self.checkout(payments=[self.cash('4.00'), self.cash('6.00')])

        self.assertEqual(txn.payments.count(), 1)
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('10.00'))

    def test_non_cash_over_tender_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'Change can only be given on cash'):
            self.checkout(payments=[self.cash('5.00'), self.card('6.00')])

    def test_card_leg_exceeding_remaining_balance_is_rejected(self):
        # 4.00 cash leaves 6.00 due; a 8.00 card leg overshoots and cannot change.
        with self.assertRaisesMessage(ValueError, 'exceeds the'):
            self.checkout(payments=[self.cash('4.00'), self.card('8.00')])

    def test_unbalanced_split_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'still due'):
            self.checkout(payments=[self.cash('4.00'), self.card('3.00')])

    def test_zero_amount_leg_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'greater than zero'):
            self.checkout(payments=[self.cash('0')])

    def test_empty_leg_list_is_rejected_by_the_validator(self):
        # process_checkout treats an empty list as "pay the full total in cash"
        # for backwards compatibility, so the guard is asserted directly.
        from .services import normalize_payments

        with self.assertRaisesMessage(ValueError, 'At least one payment'):
            normalize_payments([], Decimal('10.00'))

    def test_negative_payment_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'greater than zero'):
            self.checkout(payments=[self.cash('-5.00')])

    def test_unknown_payment_type_is_rejected(self):
        with self.assertRaisesMessage(ValueError, 'Invalid payment type'):
            self.checkout(payments=[{'payment_type': 'CRYPTO', 'amount': '10.00'}])

    def test_owner_draw_cannot_be_tendered_at_checkout(self):
        with self.assertRaisesMessage(ValueError, 'Invalid payment type'):
            self.checkout(payments=[{'payment_type': 'OWNER_DRAW', 'amount': '10.00'}])

    def test_duplicate_type_constraint_holds(self):
        txn = self.checkout(payments=[self.cash('10.00')])
        # A second row of the same type is impossible at the schema level.
        with self.assertRaises(Exception):
            Payment.objects.create(
                transaction=txn, payment_type=Payment.PaymentType.CASH, amount=Decimal('1.00')
            )


class RoundingTests(CheckoutBase):
    def test_fractional_weight_line_is_quantized_half_up(self):
        product = Product.objects.create(
            name='Tingi', category=self.category, vendor=self.vendor, sku='T-1',
            retail_price=Decimal('4.99'), cost_price=Decimal('2.00'),
            stock_quantity=Decimal('50'), is_variable_weight=True,
        )
        txn = self.checkout(
            items=[{'product_id': product.id, 'quantity': '0.555'}],
            payments=[self.cash('2.77')],
        )
        # 0.555 * 4.99 = 2.76945 -> 2.77
        self.assertEqual(txn.total_amount, Decimal('2.77'))

    def test_quantization_makes_fractional_split_add_up(self):
        product = Product.objects.create(
            name='Tingi', category=self.category, vendor=self.vendor, sku='T-2',
            retail_price=Decimal('4.99'), cost_price=Decimal('2.00'),
            stock_quantity=Decimal('50'), is_variable_weight=True,
        )
        txn = self.checkout(
            items=[{'product_id': product.id, 'quantity': '0.555'}],
            payments=[self.cash('2.77')],
        )
        # The exact-cent total means the client and server agree on the balance.
        self.assertEqual(txn.change_due, Decimal('0.00'))


class StoreCreditTests(CheckoutBase):
    def test_credit_requires_a_customer(self):
        with self.assertRaisesMessage(ValueError, 'requires a customer'):
            self.checkout(payments=[self.credit('10.00')])

    def test_only_the_credit_leg_lands_on_the_tab(self):
        txn = self.checkout(
            payments=[self.cash('6.00'), self.credit('4.00')],
            customer=self.customer,
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('4.00'))

        txn.refresh_from_db()
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('6.00'))
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.ACCOUNT), Decimal('4.00'))

    def test_credit_limit_is_checked_against_the_credit_leg_only(self):
        customer = Customer.objects.create(
            name='Tight Limit', credit_limit=Decimal('20.00'), cached_balance=Decimal('0.00'),
        )
        # 10.00 of credit fits under a 20.00 limit even though the sale is 60.00.
        items = [{'product_id': self.product.id, 'quantity': 6}]
        txn = self.checkout(
            items=items,
            payments=[self.cash('50.00'), self.credit('10.00')],
            customer=customer,
        )
        self.assertEqual(txn.total_amount, Decimal('60.00'))

        customer.refresh_from_db()
        self.assertEqual(customer.cached_balance, Decimal('10.00'))

    def test_credit_leg_over_limit_is_rejected(self):
        customer = Customer.objects.create(
            name='Tiny Limit', credit_limit=Decimal('3.00'), cached_balance=Decimal('0.00'),
        )
        with self.assertRaisesMessage(ValueError, 'Account payment denied'):
            self.checkout(
                payments=[self.cash('6.00'), self.credit('4.00')],
                customer=customer,
            )

    def test_fully_credit_sale_earns_no_loyalty_points(self):
        self.checkout(payments=[self.credit('10.00')], customer=self.customer)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.loyalty_points, 0)

    def test_split_sale_earns_points_on_cash_portion_only(self):
        # 6.00 cash of a 10.00 sale is below the 10.00-per-point threshold, so
        # no points; the credit portion must not be counted toward it.
        self.checkout(payments=[self.cash('6.00'), self.credit('4.00')], customer=self.customer)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.loyalty_points, 0)

    def test_split_sale_with_cash_above_threshold_earns_points(self):
        # A $20 sale: $16 cash clears the $10-per-point threshold on its own,
        # while counting the whole $20 would wrongly award 2 points.
        self.checkout(
            items=[{'product_id': self.product.id, 'quantity': 2}],
            payments=[self.cash('16.00'), self.credit('4.00')],
            customer=self.customer,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.loyalty_points, 1)


class VoidTests(CheckoutBase):
    def test_void_reverses_only_the_credit_leg(self):
        txn = self.checkout(
            payments=[self.cash('6.00'), self.credit('4.00')],
            customer=self.customer,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('4.00'))

        void_transaction(txn_id=txn.id, operator_user=self.admin)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('0.00'))

        txn.refresh_from_db()
        self.assertEqual(txn.status, Transaction.Status.VOIDED)

    def test_void_of_cash_sale_leaves_balance_untouched(self):
        txn = self.checkout(payments=[self.cash('10.00')], customer=self.customer)
        void_transaction(txn_id=txn.id, operator_user=self.admin)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('0.00'))

    def test_void_restores_stock(self):
        txn = self.checkout(payments=[self.cash('10.00')])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('99'))

        void_transaction(txn_id=txn.id, operator_user=self.admin)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, Decimal('100'))


class ReturnTests(CheckoutBase):
    def _post_session(self):
        self.session.status = Session.Status.POSTED
        self.session.save(update_fields=['status'])

    def test_refund_to_cash_does_not_cancel_the_tab(self):
        txn = self.checkout(
            payments=[self.cash('6.00'), self.credit('4.00')],
            customer=self.customer,
        )
        self._post_session()

        process_return(
            original_txn_id=txn.id,
            return_items=[{
                'product_id': self.product.id, 'quantity': 1,
                'price_charged': Decimal('10.00'), 'cost_price': Decimal('4.00'),
            }],
            refund_amount=Decimal('10.00'),
            refund_type=Payment.PaymentType.CASH,
            operator_user=self.admin,
        )

        # Refunding to cash pays the customer out; the tab is untouched.
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('4.00'))

    def test_refund_to_credit_reduces_the_tab(self):
        txn = self.checkout(
            payments=[self.cash('6.00'), self.credit('4.00')],
            customer=self.customer,
        )
        self._post_session()

        process_return(
            original_txn_id=txn.id,
            return_items=[{
                'product_id': self.product.id, 'quantity': 1,
                'price_charged': Decimal('10.00'), 'cost_price': Decimal('4.00'),
            }],
            refund_amount=Decimal('10.00'),
            refund_type=Payment.PaymentType.ACCOUNT,
            operator_user=self.admin,
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.cached_balance, Decimal('-6.00'))

    def test_refund_without_customer_rejects_account(self):
        txn = self.checkout(payments=[self.cash('10.00')])
        self._post_session()

        with self.assertRaisesMessage(ValueError, 'without a customer'):
            process_return(
                original_txn_id=txn.id,
                return_items=[{
                    'product_id': self.product.id, 'quantity': 1,
                    'price_charged': Decimal('10.00'), 'cost_price': Decimal('4.00'),
                }],
                refund_amount=Decimal('10.00'),
                refund_type=Payment.PaymentType.ACCOUNT,
                operator_user=self.admin,
            )


class CloseSessionCashTests(CheckoutBase):
    def test_card_sale_does_not_count_as_cash(self):
        self.checkout(payments=[self.card('10.00')])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('0.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('0.00'))

    def test_account_sale_does_not_count_as_cash(self):
        self.checkout(payments=[self.credit('10.00')], customer=self.customer)

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('0.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('0.00'))

    def test_split_counts_only_the_cash_leg(self):
        self.checkout(payments=[self.cash('4.00'), self.card('6.00')])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('4.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('4.00'))

    def test_change_given_is_netted_out(self):
        self.checkout(payments=[self.cash('20.00')])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('10.00'),
            closed_by_user=self.admin,
        )
        # 20.00 tendered, 10.00 handed back as change -> 10.00 in the drawer.
        self.assertEqual(result['expected_cash'], Decimal('10.00'))

    def test_mixed_session_totals_every_cash_source(self):
        self.checkout(payments=[self.cash('10.00')])
        self.checkout(payments=[self.cash('4.00'), self.card('6.00')])
        self.checkout(payments=[self.card('10.00')])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('14.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('14.00'))

    def test_cash_refund_reduces_expected_cash(self):
        txn = self.checkout(payments=[self.cash('20.00')])
        self.session.status = Session.Status.POSTED
        self.session.save(update_fields=['status'])

        process_return(
            original_txn_id=txn.id,
            return_items=[{
                'product_id': self.product.id, 'quantity': 1,
                'price_charged': Decimal('10.00'), 'cost_price': Decimal('4.00'),
            }],
            refund_amount=Decimal('10.00'),
            refund_type=Payment.PaymentType.CASH,
            operator_user=self.admin,
        )

        # The refund belongs to the now-POSTED session, so reopen a session and
        # move it there is not possible; instead verify the sign on the session
        # that actually holds the refund.
        self.session.status = Session.Status.OPEN
        self.session.save(update_fields=['status'])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('0.00'),
            closed_by_user=self.admin,
        )
        # 20.00 tendered - 10.00 change = 10.00 kept, minus 10.00 refunded.
        self.assertEqual(result['expected_cash'], Decimal('0.00'))

    def test_voided_sale_excluded_from_expected_cash(self):
        txn = self.checkout(payments=[self.cash('10.00')])
        void_transaction(txn_id=txn.id, operator_user=self.admin)

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('0.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('0.00'))

    def test_starting_cash_is_included(self):
        self.session.starting_cash = Decimal('50.00')
        self.session.save(update_fields=['starting_cash'])

        self.checkout(payments=[self.cash('10.00')])

        result = close_session(
            session_id=self.session.id, actual_cash=Decimal('60.00'),
            closed_by_user=self.admin,
        )
        self.assertEqual(result['expected_cash'], Decimal('60.00'))


class LedgerTests(CheckoutBase):
    def test_split_sale_writes_one_ledger_entry_for_the_full_total(self):
        txn = self.checkout(payments=[self.cash('4.00'), self.card('6.00')])

        entries = Ledger.objects.filter(transaction=txn, entry_type='SALE')
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().amount, Decimal('10.00'))


class ReceiptTests(CheckoutBase):
    def test_split_receipt_lists_each_tender_and_change(self):
        from .receipts import build_receipt_lines

        txn = self.checkout(payments=[self.card('4.00'), self.cash('8.00')])
        lines = build_receipt_lines(txn)

        self.assertTrue(any(line.startswith('Cash') and '8.00' in line for line in lines))
        self.assertTrue(any(line.startswith('Card') and '4.00' in line for line in lines))
        self.assertTrue(any(line.startswith('CHANGE') and '2.00' in line for line in lines))
        # The old single-payment 'PAID' summary line is gone.
        self.assertFalse(any(line.startswith('PAID') for line in lines))

    def test_single_payment_receipt_has_one_tender_line(self):
        from .receipts import build_receipt_lines

        txn = self.checkout(payments=[self.cash('10.00')])
        lines = build_receipt_lines(txn)

        self.assertTrue(any(line.startswith('Cash') for line in lines))
        self.assertFalse(any(line.startswith('CHANGE') for line in lines))

    def test_thermal_receipt_includes_receipt_notes(self):
        from .receipts import build_receipt_lines

        BusinessInfo.objects.create(
            business_name='Test Shop',
            receipt_notes='Thanks for shopping with us!',
        )
        txn = self.checkout(payments=[self.cash('10.00')])
        lines = build_receipt_lines(txn)

        self.assertTrue(any('Thanks for shopping with us!' in line for line in lines))


class OfflineRecoveryPaymentTests(CheckoutBase):
    def test_recovery_creates_a_single_payment_row(self):
        from .services import batch_offline_recovery

        batch_offline_recovery(
            rows=[{
                'total_amount': '25.00',
                'payment_amount': '25.00',
                'payment_type': Payment.PaymentType.CARD,
                'transaction_date': timezone.now(),
                'items': [{
                    'product_id': self.product.id, 'quantity': '2.5',
                    'price': '10.00', 'cost_price': '4.00',
                }],
            }],
            operator_user=self.admin,
        )

        txn = Transaction.objects.get()
        self.assertEqual(txn.total_amount, Decimal('25.00'))
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CARD), Decimal('25.00'))


class SplitCheckoutViewTests(CheckoutBase):
    """End-to-end coverage of the split tender through the request/response
    stack: the checkout page, the payments_json payload, and every template
    that renders a tender breakdown."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        BusinessInfo.objects.create(business_name='Test Shop')

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def _fill_cart(self, quantity=1):
        session = self.client.session
        session['cart'] = [{
            'product_id': self.product.id,
            'product_name': self.product.name,
            'sku': self.product.sku,
            'price': float(self.product.retail_price),
            'quantity': quantity,
            'stock': float(self.product.stock_quantity),
        }]
        session.save()

    def _split_payments_json(self, legs):
        return json.dumps([{'payment_type': t, 'amount': a} for t, a in legs])

    def test_checkout_page_renders_split_payment_controls(self):
        response = self.client.get(reverse('sales:checkout'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'payments_json')

    def test_split_payments_json_creates_two_tender_rows(self):
        self._fill_cart()
        response = self.client.post(reverse('sales:checkout_complete'), {
            'payments_json': self._split_payments_json([
                (Payment.PaymentType.CARD, '4.00'),
                (Payment.PaymentType.CASH, '8.00'),
            ]),
        })

        txn = Transaction.objects.get()
        self.assertRedirects(response, reverse('sales:receipt', kwargs={'pk': txn.pk}))
        self.assertEqual(txn.payments.count(), 2)
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CASH), Decimal('8.00'))
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CARD), Decimal('4.00'))
        self.assertEqual(txn.change_due, Decimal('2.00'))

    def test_missing_payments_json_falls_back_to_single_full_tender(self):
        self._fill_cart()
        self.client.post(reverse('sales:checkout_complete'), {'payment_type': Payment.PaymentType.CARD})

        txn = Transaction.objects.get()
        self.assertEqual(txn.payments.count(), 1)
        self.assertEqual(txn.payment_amount_for(Payment.PaymentType.CARD), Decimal('10.00'))

    def test_client_underpayment_is_rejected_against_server_total(self):
        self._fill_cart()
        self.client.post(reverse('sales:checkout_complete'), {
            # The cart is worth 10.00; a client claiming 1.00 must not post.
            'payments_json': self._split_payments_json([(Payment.PaymentType.CASH, '1.00')]),
        })

        self.assertFalse(Transaction.objects.exists())

    def test_receipt_template_renders_each_tender(self):
        txn = self.checkout(payments=[self.card('4.00'), self.cash('8.00')])
        response = self.client.get(reverse('sales:receipt', kwargs={'pk': txn.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['payments']), list(txn.payments.all()))
        self.assertEqual(response.context['change'], Decimal('2.00'))
        self.assertContains(response, 'Card')
        self.assertContains(response, 'Cash')

    def test_receipt_template_shows_receipt_notes(self):
        biz = BusinessInfo.objects.first()
        biz.receipt_notes = 'Store policies apply.'
        biz.save(update_fields=['receipt_notes'])
        txn = self.checkout(payments=[self.cash('10.00')])
        response = self.client.get(reverse('sales:receipt', kwargs={'pk': txn.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Store policies')

    def test_receipt_template_drops_hardcoded_thank_you_line(self):
        biz = BusinessInfo.objects.first()
        biz.receipt_notes = 'Store policies apply.'
        biz.save(update_fields=['receipt_notes'])
        txn = self.checkout(payments=[self.cash('10.00')])
        response = self.client.get(reverse('sales:receipt', kwargs={'pk': txn.pk}))

        self.assertNotContains(response, 'Please keep this receipt')

    def test_thermal_receipt_drops_hardcoded_thank_you_line(self):
        from .receipts import build_receipt_lines

        biz = BusinessInfo.objects.first()
        biz.receipt_notes = 'Thanks for shopping with us!'
        biz.save(update_fields=['receipt_notes'])
        txn = self.checkout(payments=[self.cash('10.00')])
        lines = build_receipt_lines(txn)

        self.assertFalse(any('THANK YOU' in line for line in lines))
        self.assertFalse(any('KEEP THIS RECEIPT' in line for line in lines))
        self.assertTrue(any('Thanks for shopping with us!' in line for line in lines))

    def test_transaction_detail_renders_tender_breakdown(self):
        txn = self.checkout(payments=[self.card('4.00'), self.cash('8.00')])
        response = self.client.get(reverse('sales:transaction_detail', kwargs={'pk': txn.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Card')
        self.assertContains(response, 'Cash')
        self.assertContains(response, 'Reprint Receipt')
        self.assertContains(
            response,
            f'href="{reverse("sales:receipt", kwargs={"pk": txn.pk})}"',
        )

    def test_customer_detail_renders_tender_breakdown(self):
        txn = self.checkout(payments=[self.credit('6.00'), self.cash('4.00')], customer=self.customer)
        response = self.client.get(reverse('customers:customer_detail', kwargs={'pk': self.customer.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account')
        self.assertContains(response, 'Cash')



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


class ArchivedProductSalesTests(CheckoutBase):
    """An archived product must be unsellable through every sales path, while
    the sale history that already references it stays intact."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Without this, SetupCheckMiddleware 302s every request to /setup/.
        BusinessInfo.objects.get_or_create(business_name='Test Shop')

    def setUp(self):
        super().setUp()
        self.gone = Product.objects.create(
            name='Discontinued Widget', category=self.category, vendor=self.vendor,
            sku='W-99', retail_price=Decimal('10.00'), cost_price=Decimal('4.00'),
            stock_quantity=Decimal('50'),
        )
        self.archive(self.gone)

    def archive(self, product):
        product.is_active = False
        product.save(update_fields=['is_active'])

    def cart_add(self, product):
        return self.client.post(
            reverse('sales:cart_add'),
            {'product_id': product.id},
        )

    # --- search / cart ----------------------------------------------------

    def test_checkout_search_hides_archived(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('sales:product_search'), {'q': 'Discontinued'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'W-99')

    def test_cart_add_rejects_archived_product(self):
        self.client.force_login(self.admin)
        resp = self.cart_add(self.gone)
        self.assertEqual(resp.status_code, 404)
        session = self.client.session
        self.assertEqual(session.get('cart', []), [])

    def test_cart_add_still_accepts_live_product(self):
        self.client.force_login(self.admin)
        resp = self.cart_add(self.product)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [line['product_id'] for line in self.client.session['cart']],
            [self.product.id],
        )

    def test_checkout_page_drops_archived_lines_from_an_open_cart(self):
        # The product is archived while it sits in the cart, so the search
        # filters never ran for it.
        session = self.client.session
        session['cart'] = [{
            'product_id': self.gone.id, 'product_name': self.gone.name,
            'sku': 'W-99', 'price': 10.0, 'quantity': 1, 'stock': 50.0,
        }]
        session.save()
        self.client.force_login(self.admin)

        resp = self.client.get(reverse('sales:checkout'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['cart'], [])
        self.assertEqual(self.client.session['cart'], [])

    # --- checkout ---------------------------------------------------------

    def test_process_checkout_rejects_archived_product(self):
        with self.assertRaises(ValueError) as ctx:
            self.checkout(payments=[self.cash('10.00')],
                          items=[{'product_id': self.gone.id, 'quantity': 1}])
        self.assertIn('Discontinued Widget', str(ctx.exception))
        self.assertEqual(Transaction.objects.count(), 0)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('50'))

    def test_checkout_complete_view_rejects_archived_product(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('sales:checkout_complete'), {
            'cart_json': json.dumps([{
                'product_id': self.gone.id, 'product_name': self.gone.name,
                'sku': 'W-99', 'price': 10.0, 'quantity': 1, 'stock': 50,
            }]),
            'payment_type': Payment.PaymentType.CASH,
            'payments_json': json.dumps([
                {'payment_type': Payment.PaymentType.CASH, 'amount': 10.0},
            ]),
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 0)
        self.gone.refresh_from_db()
        self.assertEqual(self.gone.stock_quantity, Decimal('50'))

    # --- offline recovery -------------------------------------------------

    def test_offline_recovery_rejects_archived_product(self):
        from .services import batch_offline_recovery

        with self.assertRaises(ValueError) as ctx:
            batch_offline_recovery(
                rows=[{
                    'total_amount': '10.00',
                    'payment_amount': '10.00',
                    'payment_type': Payment.PaymentType.CASH,
                    'transaction_date': timezone.now(),
                    'items': [{
                        'product_id': self.gone.id, 'quantity': '1',
                        'price': '10.00', 'cost_price': '4.00',
                    }],
                }],
                operator_user=self.admin,
            )
        self.assertIn('Discontinued Widget', str(ctx.exception))
        self.assertEqual(Transaction.objects.count(), 0)
        # The virtual session must not be left behind either.
        self.assertEqual(Session.objects.filter(status=Session.Status.POSTED).count(), 0)

    def test_offline_recovery_page_hides_archived_lookup_entries(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('sales:offline_recovery'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'W-99')

    # --- bundles ----------------------------------------------------------

    def test_checkout_drops_archived_bundle_components(self):
        bundle = Bundle.objects.create(name='Discontinued Mix')
        BundleItem.objects.create(bundle=bundle, product=self.gone, quantity=Decimal('1'))
        self.client.force_login(self.admin)

        resp = self.client.get(reverse('sales:checkout'))
        self.assertEqual(resp.context['bundles'], [])

    def test_bundle_keeps_only_live_components(self):
        bundle = Bundle.objects.create(name='Mixed')
        BundleItem.objects.create(bundle=bundle, product=self.product, quantity=Decimal('1'))
        BundleItem.objects.create(bundle=bundle, product=self.gone, quantity=Decimal('1'))
        self.client.force_login(self.admin)

        resp = self.client.get(reverse('sales:checkout'))
        bundles = resp.context['bundles']
        self.assertEqual(len(bundles), 1)
        self.assertEqual([i['product_id'] for i in bundles[0]['items']], [self.product.id])

    # --- history ----------------------------------------------------------

    def test_past_sale_still_readable_after_the_product_is_archived(self):
        txn = process_checkout(
            session_id=self.session.id,
            items=[{'product_id': self.product.id, 'quantity': 1}],
            payments=[self.cash('10.00')],
            operator_user=self.admin,
        )
        self.archive(self.product)

        self.client.force_login(self.admin)
        resp = self.client.get(reverse('sales:receipt', args=[txn.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.product.name)
        # And it is gone from the screens that would let it be sold again.
        search = self.client.get(reverse('sales:product_search'), {'q': 'Widget'})
        self.assertNotContains(search, self.product.sku)
