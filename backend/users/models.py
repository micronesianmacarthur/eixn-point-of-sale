from django.db import models
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    class Role(models.TextChoices):
        CASHIER = 'CASHIER', 'Cashier'
        MANAGER = 'MANAGER', 'Manager'
        ADMIN = 'ADMIN', 'Admin'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.CASHIER,
    )
    pin_code = models.CharField(max_length=128, blank=True, help_text='Hashed PIN for cashier auth')
    address_1 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True)

    def set_pin_code(self, raw_pin):
        self.pin_code = make_password(raw_pin)

    def save(self, *args, **kwargs):
        self.username = self.username.lower()
        if self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_superuser = True
        super().save(*args, **kwargs)

    @property
    def is_cashier(self):
        return self.role in (self.Role.CASHIER, self.Role.MANAGER, self.Role.ADMIN)

    @property
    def is_manager(self):
        return self.role in (self.Role.MANAGER, self.Role.ADMIN)

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN
