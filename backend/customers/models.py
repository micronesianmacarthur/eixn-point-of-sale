from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    allow_pay_later = models.BooleanField(default=False)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_owner = models.BooleanField(default=False)
    cached_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    loyalty_points = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    loyalty_enabled = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.CheckConstraint(
                check=models.Q(is_owner=True) | models.Q(cached_balance__lte=models.F('credit_limit')),
                name='check_credit_limit_boundary',
            )
        ]

    def __str__(self):
        return self.name

    def has_available_credit(self, amount):
        if self.is_owner:
            return True
        return (self.cached_balance + amount) <= self.credit_limit


class CreditProfile(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='credit_profile')
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    settlement_period_days = models.IntegerField(default=30)

    def __str__(self):
        return f'{self.customer.name}: ${self.current_balance} / ${self.credit_limit}'
