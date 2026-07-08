from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class UserManagementDeleteTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="manager1",
            password="StrongPass123!",
            role=User.Role.MANAGER,
        )
        self.admin = User.objects.create_user(
            username="admin1",
            password="StrongPass123!",
            role=User.Role.ADMIN,
        )
        self.cashier = User.objects.create_user(
            username="cashier1",
            password="StrongPass123!",
            role=User.Role.CASHIER,
        )

    def test_manager_sees_delete_button_on_user_list(self):
        self.client.force_login(self.manager)

        response: HttpResponse = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("users:user_delete", args=[self.cashier.pk])
        )
        self.assertContains(response, "Delete")

    def test_manager_can_delete_another_user(self):
        self.client.force_login(self.manager)

        response: HttpResponse = self.client.post(
            reverse("users:user_delete", args=[self.cashier.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=self.cashier.pk).exists())

    def test_user_cannot_delete_self(self):
        self.client.force_login(self.manager)

        response: HttpResponse = self.client.post(
            reverse("users:user_delete", args=[self.manager.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.manager.pk).exists())
        self.assertContains(response, "You cannot delete your own account.")

    def test_last_admin_cannot_be_deleted(self):
        self.client.force_login(self.manager)

        response: HttpResponse = self.client.post(
            reverse("users:user_delete", args=[self.admin.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertContains(response, "Cannot delete the last admin account.")
