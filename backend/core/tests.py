import gzip
import json
import os
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, TransactionTestCase
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


class LocalBackupTests(TestCase):
    """Tests for the local_backup management command."""

    @classmethod
    def setUpTestData(cls):
        # Point DATABASE_URL at the throwaway test DB (same host/port/user as
        # the dev DB, database name prefixed with 'test_' by Django's test runner).
        dev_url = os.environ.get("DATABASE_URL", "")
        if dev_url.startswith("postgres"):
            cls.test_db_url = dev_url.rsplit("/", 1)[0] + "/test_eixn_pos"
        else:
            cls.test_db_url = dev_url

    def _run_backup(self):
        with patch.dict(os.environ, {"DATABASE_URL": self.test_db_url}):
            return call_command("local_backup", verbosity=0)

    def test_local_backup_creates_valid_gzip(self):
        out = self._run_backup()
        backup_dir = Path(settings.BASE_DIR) / "backups"
        gz_files = list(backup_dir.glob("eixn_pos_*.sql.gz"))
        self.assertTrue(gz_files, "No .sql.gz backup file was created")
        latest = max(gz_files, key=lambda p: p.stat().st_mtime)
        # Valid gzip
        with gzip.open(latest, "rb") as f:
            self.assertTrue(f.read(2), "Backup file is not valid gzip")
        # last_backup.txt marker written
        marker = Path(settings.BASE_DIR) / "last_backup.txt"
        self.assertTrue(marker.exists())
        import json
        data = json.loads(marker.read_text())
        self.assertFalse(data["uploaded"])
        self.assertIsNotNone(data["local_file"])
        # Cleanup
        latest.unlink(missing_ok=True)

    def test_local_backup_raises_on_bad_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///bad.db"}):
            with self.assertRaises(CommandError):
                call_command("local_backup", verbosity=0)


class LocalRestoreTests(TransactionTestCase):
    """Tests for the local_restore management command."""

    def setUp(self):
        dev_url = os.environ.get("DATABASE_URL", "")
        if dev_url.startswith("postgres"):
            self.test_db_url = dev_url.rsplit("/", 1)[0] + "/test_eixn_pos"
        else:
            self.test_db_url = dev_url
        BusinessInfo.objects.create(business_name="Before Restore")

    def test_local_restore_restores_data(self):
        backup_path = Path(settings.BASE_DIR) / "backups" / "eixn_pos_latest_test.sql.gz"
        with patch.dict(os.environ, {"DATABASE_URL": self.test_db_url}):
            call_command("local_backup", output=backup_path, verbosity=0)
            # Wipe the data, then restore
            BusinessInfo.objects.all().delete()
            self.assertIsNone(BusinessInfo.objects.first())
            call_command("local_restore", backup_path, verbosity=0)
        biz = BusinessInfo.objects.first()
        self.assertIsNotNone(biz)
        self.assertEqual(biz.business_name, "Before Restore")
        backup_path.unlink(missing_ok=True)