from django.test import TestCase
from django.urls import reverse

from users.models import User

from .models import BusinessInfo


def _settings_post(receipt_notes):
    return {
        'default_markup_rate': '0.15',
        'session_idle_timeout_enabled': 'on',
        'session_idle_timeout': '5',
        'default_customer_credit_limit': '0.00',
        'receipt_notes': receipt_notes,
    }


class ReceiptNoteSettingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', password='pass', role=User.Role.ADMIN
        )
        cls.cashier = User.objects.create_user(
            username='cashier', password='pass', role=User.Role.CASHIER
        )
        BusinessInfo.objects.create(
            business_name='Test Shop', contact_phone='555-0100'
        )

    def test_manager_sees_receipt_tab_and_can_save_note(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Receipt')
        self.assertContains(response, 'name="receipt_notes"')

        response = self.client.post(
            reverse('settings'), _settings_post('Thank you for shopping!')
        )
        self.assertEqual(response.status_code, 302)

        biz = BusinessInfo.objects.first()
        self.assertEqual(biz.receipt_notes, 'Thank you for shopping!')

    def test_cashier_does_not_get_receipt_tab_or_note_save(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse('settings'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="receipt_notes"')

        self.client.post(reverse('settings'), _settings_post('Hacked note'))
        biz = BusinessInfo.objects.first()
        self.assertEqual(biz.receipt_notes, '')