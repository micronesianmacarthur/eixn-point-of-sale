from django.contrib import admin

from .models import Bundle, BundleItem, Category, InventoryReceipt, InventoryReceiptItem, Product, PurchaseOrder, PurchaseOrderItem, RecipeIngredient, Vendor


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    fk_name = 'parent_product'
    extra = 1


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'email')
    search_fields = ('name',)
    actions = ['delete_selected']


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'vendor', 'stock_quantity', 'min_stock_level', 'retail_price', 'is_on_sale', 'is_service', 'is_variable_weight')
    list_filter = ('vendor', 'is_on_sale', 'is_service', 'is_variable_weight')
    search_fields = ('sku', 'name')
    inlines = [RecipeIngredientInline]
    actions = ['delete_selected']


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    list_display = ('parent_product', 'child_product', 'quantity_required')
    list_filter = ('parent_product',)
    actions = ['delete_selected']


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'vendor', 'status', 'created_by', 'created_at')
    list_filter = ('status',)
    inlines = [PurchaseOrderItemInline]
    actions = ['delete_selected']


class InventoryReceiptItemInline(admin.TabularInline):
    model = InventoryReceiptItem
    extra = 1


@admin.register(InventoryReceipt)
class InventoryReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'vendor', 'received_by', 'received_at', 'funded_by_owner', 'total_cost')
    list_filter = ('funded_by_owner',)
    inlines = [InventoryReceiptItemInline]
    actions = ['delete_selected']


@admin.register(InventoryReceiptItem)
class InventoryReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'inventory_receipt', 'product', 'quantity', 'cost_price_at_receiving')
    actions = ['delete_selected']


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'purchase_order', 'product', 'quantity')
    actions = ['delete_selected']


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    extra = 1


@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ('name', 'retail_price', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    inlines = [BundleItemInline]
    actions = ['delete_selected']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    actions = ['delete_selected']
