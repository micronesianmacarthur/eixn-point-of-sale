from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from users.models import User


class Vendor(models.Model):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name


class RecipeIngredient(models.Model):
    parent_product = models.ForeignKey('Product', on_delete=models.PROTECT, related_name='recipe_ingredients')
    child_product = models.ForeignKey('Product', on_delete=models.PROTECT, related_name='used_in_recipes')
    quantity_required = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = ('parent_product', 'child_product')

    def __str__(self):
        return f'{self.parent_product.name} needs {self.child_product.name} x{self.quantity_required}'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    sku = models.CharField(max_length=100, unique=True, blank=True)
    name = models.CharField(max_length=200)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    retail_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    is_on_sale = models.BooleanField(default=False)
    is_service = models.BooleanField(default=False, help_text='100% margin service item')
    is_variable_weight = models.BooleanField(default=False, help_text='Tingi fractional quantity item')
    stock_quantity = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    min_stock_level = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    components = models.ManyToManyField('self', through=RecipeIngredient, symmetrical=False)

    def __str__(self):
        return f'{self.sku} — {self.name}'


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        SENT = 'SENT', 'Sent'
        RECEIVED = 'RECEIVED', 'Received'
        CANCELLED = 'CANCELLED', 'Cancelled'

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='purchase_orders')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='purchase_orders')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    def __str__(self):
        return f'PO-{self.id} ({self.vendor.name})'


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_order_items')
    quantity = models.IntegerField()

    def __str__(self):
        return f'{self.product.name} x{self.quantity}'


class InventoryReceipt(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts')
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='receipts')
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='receipts')
    received_at = models.DateTimeField(auto_now_add=True)
    funded_by_owner = models.BooleanField(default=False)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0.00)
    owner_contribution_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    owner_customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='receipts')
    receipt_number = models.CharField(max_length=100, blank=True, default='')

    def __str__(self):
        return f'RCPT-{self.id} ({self.vendor.name})'


class InventoryReceiptItem(models.Model):
    inventory_receipt = models.ForeignKey(InventoryReceipt, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='receipt_items')
    quantity = models.IntegerField()
    cost_price_at_receiving = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f'{self.product.name} x{self.quantity} @ ${self.cost_price_at_receiving}'


class InventoryStockCount(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        POSTED = 'POSTED', 'Posted'

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='stock_counts')
    note = models.TextField(blank=True, default='')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f'COUNT-{self.id} ({self.get_status_display()})'


class InventoryAdjustment(models.Model):
    class Reason(models.TextChoices):
        PHYSICAL_COUNT = 'PHYSICAL_COUNT', 'Physical count'
        DAMAGED = 'DAMAGED', 'Damaged goods'
        EXPIRED = 'EXPIRED', 'Expired'
        FOUND = 'FOUND', 'Found on shelf'
        SHRINKAGE = 'SHRINKAGE', 'Shrinkage'
        OTHER = 'OTHER', 'Other'

    stock_count = models.ForeignKey(InventoryStockCount, on_delete=models.PROTECT, null=True, blank=True, related_name='adjustments')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_adjustments')
    previous_qty = models.DecimalField(max_digits=10, decimal_places=3)
    adjusted_qty = models.DecimalField(max_digits=10, decimal_places=3)
    delta = models.DecimalField(max_digits=10, decimal_places=3)
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.PHYSICAL_COUNT)
    cost_price_at_adjustment = models.DecimalField(max_digits=12, decimal_places=2)
    delta_cost_value = models.DecimalField(max_digits=14, decimal_places=2)
    adjusted_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='stock_adjustments')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.product.sku} — {self.get_reason_display()}'


class Bundle(models.Model):
    name = models.CharField(max_length=200, verbose_name=_('Name'))
    description = models.TextField(blank=True, verbose_name=_('Description'))
    retail_price = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        verbose_name=_('Retail Price'),
        help_text=_('Fixed bundle price. If empty, price = sum of component prices.'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    class Meta:
        verbose_name = _('Bundle')
        verbose_name_plural = _('Bundles')

    def __str__(self):
        return self.name


class BundleItem(models.Model):
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name='items', verbose_name=_('Bundle'))
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='bundles', verbose_name=_('Product'))
    quantity = models.DecimalField(max_digits=10, decimal_places=3, default=1, verbose_name=_('Quantity'))

    class Meta:
        verbose_name = _('Bundle Item')
        verbose_name_plural = _('Bundle Items')
        unique_together = ('bundle', 'product')

    def __str__(self):
        return f'{self.product.name} x{self.quantity}'
