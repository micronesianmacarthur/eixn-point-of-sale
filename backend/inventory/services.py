import csv
import io
from decimal import Decimal

from django.db import models, transaction

from accounting.services import process_owner_contribution
from customers.models import Customer

from .models import Category, InventoryReceipt, InventoryReceiptItem, Product, PurchaseOrder, RecipeIngredient, Vendor


@transaction.atomic
def deduct_composite(product_id, quantity):
    ingredients = list(
        RecipeIngredient.objects.filter(
            parent_product_id=product_id,
            child_product__is_service=False,
        ).select_related('child_product').select_for_update()
    )
    if ingredients:
        for ing in ingredients:
            qty = ing.quantity_required * Decimal(str(quantity))
            Product.objects.filter(id=ing.child_product_id).update(
                stock_quantity=models.F('stock_quantity') - qty
            )
    else:
        Product.objects.filter(id=product_id, is_service=False).update(
            stock_quantity=models.F('stock_quantity') - Decimal(str(quantity))
        )


@transaction.atomic
def receive_inventory(
    *,
    vendor,
    received_by,
    items,
    purchase_order=None,
    funded_by_owner=False,
    business_cash_amount=Decimal('0.00'),
    owner_contribution_amount=Decimal('0.00'),
    owner_customer_id=None,
    receipt_number='',
    session=None,
    operator_user=None,
):
    total_cost = sum(
        (Decimal(str(item['quantity'])) * item['cost_price'] for item in items),
        Decimal('0.00')
    )

    receipt = InventoryReceipt.objects.create(
        purchase_order=purchase_order,
        vendor=vendor,
        received_by=received_by,
        funded_by_owner=funded_by_owner,
        owner_contribution_amount=owner_contribution_amount,
        owner_customer_id=owner_customer_id,
        receipt_number=receipt_number,
        total_cost=total_cost,
    )

    for item in items:
        InventoryReceiptItem.objects.create(
            inventory_receipt=receipt,
            product_id=item['product_id'],
            quantity=item['quantity'],
            cost_price_at_receiving=item['cost_price'],
        )
        Product.objects.filter(id=item['product_id'], is_service=False).update(
            stock_quantity=models.F('stock_quantity') + item['quantity']
        )

    if owner_contribution_amount > 0 and owner_customer_id and session and operator_user:
        owner_customer = Customer.objects.get(id=owner_customer_id)
        process_owner_contribution(
            session=session,
            owner_customer=owner_customer,
            operator_user=operator_user,
            contribution_amount=owner_contribution_amount,
        )

    if purchase_order:
        purchase_order.status = PurchaseOrder.Status.RECEIVED
        purchase_order.save(update_fields=['status'])

    return receipt


BULK_REQUIRED_HEADERS = ["vendor_name", "name"]
BULK_OPTIONAL_HEADERS = [
    "category_name", "cost_price", "retail_price", "discount_price",
    "is_on_sale", "is_service", "is_variable_weight",
    "stock_quantity", "min_stock_level",
    "child_sku", "child_qty",
]


@transaction.atomic
def bulk_seed_products_csv(csv_text, *, dry_run=False, received_by=None):
    """
    Parse CSV text and bulk-create Product / RecipeIngredient records.

    For non-service products with stock_quantity > 0, InventoryReceipt records
    are created automatically (grouped by vendor).

    Returns a dict with counts and any error/skip messages.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or has no headers")

    missing = [h for h in BULK_REQUIRED_HEADERS if h not in reader.fieldnames]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")

    rows = list(reader)
    report = {"total": len(rows), "products": 0, "vendors": 0, "recipes": 0, "receipts": 0, "skipped": [], "errors": []}

    # Vendor cache — all text uppercased
    vendor_names = {r["vendor_name"].strip().upper() for r in rows if r["vendor_name"].strip()}
    existing_vendors = {v.name: v for v in Vendor.objects.filter(name__in=vendor_names)}
    new_vendors = []
    for name in sorted(vendor_names):
        if name not in existing_vendors:
            v = Vendor(name=name)
            new_vendors.append(v)
            existing_vendors[name] = v

    if new_vendors and not dry_run:
        Vendor.objects.bulk_create(new_vendors)
    report["vendors"] = len(new_vendors)

    # Products
    recipe_edges = []
    product_by_sku = {}
    product_objs = []

    # Category cache — all text uppercased
    category_names = {r.get("category_name", "").strip().upper() for r in rows if r.get("category_name", "").strip()}
    existing_categories = {c.name: c for c in Category.objects.filter(name__in=category_names)}
    for name in sorted(category_names):
        if name not in existing_categories:
            c = Category(name=name)
            existing_categories[name] = c
    new_categories = [c for c in existing_categories.values() if c.pk is None]
    if new_categories and not dry_run:
        Category.objects.bulk_create(new_categories)
        for c in Category.objects.filter(name__in=category_names):
            existing_categories[c.name] = c

    for i, row in enumerate(rows):
        vendor_name = row.get("vendor_name", "").strip()
        if not vendor_name:
            report["errors"].append(f"Row {i + 1}: vendor_name is required")
            continue
        sku = row.get("sku", "").strip()
        vendor = existing_vendors.get(vendor_name.upper())
        category_name = row.get("category_name", "").strip().upper()
        category = existing_categories.get(category_name) if category_name else None

        try:
            product = Product(
                vendor=vendor,
                category=category,
                sku=sku or f'_TEMP_{i}',
                name=row["name"].strip().upper(),
                cost_price=_parse_decimal(row["cost_price"]),
                retail_price=_parse_decimal(row["retail_price"]),
                discount_price=_parse_decimal(row.get("discount_price", "")),
                is_on_sale=row.get("is_on_sale", "").strip().lower() in ("1", "yes", "true", "y"),
                is_service=row.get("is_service", "").strip().lower() in ("1", "yes", "true", "y"),
                is_variable_weight=row.get("is_variable_weight", "").strip().lower() in ("1", "yes", "true", "y"),
                stock_quantity=_parse_decimal(row.get("stock_quantity", "0")),
                min_stock_level=_parse_decimal(row.get("min_stock_level", "0")),
            )
        except Exception as exc:
            report["errors"].append(f"Row {i + 1}: {exc}")
            continue

        product_objs.append(product)
        product_by_sku[sku or f'_TEMP_{i}'] = product

        child_sku = row.get("child_sku", "").strip()
        if child_sku:
            recipe_edges.append((sku or f'_TEMP_{i}', child_sku, _parse_decimal(row.get("child_qty", "0"))))

    if not dry_run:
        Product.objects.bulk_create(product_objs)
        report["products"] = len(product_objs)

        # Generate SKUs for products that didn't have one
        temp_rows = [(i, r) for i, r in enumerate(rows) if not r.get("sku", "").strip()]
        if temp_rows:
            temp_skus = [f'_TEMP_{i}' for i, _ in temp_rows]
            temp_products = {p.sku: p for p in Product.objects.filter(sku__in=temp_skus)}
            for i, r in temp_rows:
                p = temp_products.get(f'_TEMP_{i}')
                if p:
                    cat_name = r.get("category_name", "").strip().upper()
                    if cat_name and cat_name in existing_categories:
                        p.sku = generate_sku(existing_categories[cat_name].name, p.id)
                    else:
                        p.sku = f'GEN-{p.id:04d}'
            if temp_products:
                Product.objects.bulk_update(temp_products.values(), ['sku'])

        # Refresh — re-read all created products
        product_by_sku.clear()
        created = Product.objects.filter(id__in=[p.id for p in product_objs])
        for p in created:
            product_by_sku[p.sku] = p

        # Inventory receipts — group by vendor for non-service products with stock
        stock_by_vendor = {}
        for p in created:
            if not p.is_service and p.stock_quantity > 0:
                stock_by_vendor.setdefault(p.vendor, []).append(p)
        for vendor, products in stock_by_vendor.items():
            total_cost = sum(p.cost_price * p.stock_quantity for p in products)
            receipt = InventoryReceipt.objects.create(
                vendor=vendor,
                received_by=received_by,
                total_cost=total_cost,
            )
            InventoryReceiptItem.objects.bulk_create([
                InventoryReceiptItem(
                    inventory_receipt=receipt,
                    product=p,
                    quantity=int(p.stock_quantity),
                    cost_price_at_receiving=p.cost_price,
                )
                for p in products
            ])
            report["receipts"] += 1

        # Recipe ingredients
        ingredients = []
        for parent_sku, child_sku, qty in recipe_edges:
            parent = product_by_sku.get(parent_sku)
            child = product_by_sku.get(child_sku)
            if parent and child:
                ingredients.append(RecipeIngredient(parent_product=parent, child_product=child, quantity=qty))
            else:
                report["skipped"].append(f"Recipe link {parent_sku} -> {child_sku} (missing product)")

        if ingredients:
            RecipeIngredient.objects.bulk_create(ingredients)
        report["recipes"] = len(ingredients)
    else:
        report["products"] = len(product_objs)
        report["recipes"] = len(recipe_edges)

    return report


VOWELS = frozenset('aeiou')


@transaction.atomic
def execute_repack(parent_product_id, parent_qty_to_consume):
    """
    Consume `parent_qty_to_consume` units of a bulk parent product and
    create the equivalent child-product stock based on RecipeIngredient ratios.

    Returns a summary dict.
    """
    parent = Product.objects.select_for_update().get(id=parent_product_id)
    ingredients = list(
        RecipeIngredient.objects.filter(parent_product=parent).select_related('child_product')
    )

    if not ingredients:
        raise ValueError(f'No child breakdown defined for "{parent.name}".')

    qty = Decimal(str(parent_qty_to_consume))
    if parent.stock_quantity < qty:
        raise ValueError(
            f'Not enough stock of "{parent.name}". '
            f'Available: {parent.stock_quantity}, needed: {qty}'
        )

    parent.stock_quantity -= qty
    parent.save(update_fields=['stock_quantity'])

    children_summary = []
    for ing in ingredients:
        child_qty = ing.quantity_required * qty
        Product.objects.filter(id=ing.child_product_id).update(
            stock_quantity=models.F('stock_quantity') + child_qty
        )
        children_summary.append({
            'name': ing.child_product.name,
            'qty': child_qty,
        })

    return {
        'parent': parent.name,
        'parent_consumed': qty,
        'parent_remaining': parent.stock_quantity,
        'children': children_summary,
    }


def generate_sku(category_name, product_id):
    """
    Generate SKU: first letter of category name + next 2 consonants
    (padded with 'x' if needed), hyphen, zero-padded 4-digit product ID
    (8 chars total).

    Examples:
        category='Electronics', id=1   -> 'elc-0001'
        category='Beverages',   id=42  -> 'bvr-0042'
        category='Utility',     id=7   -> 'utl-0007'
        category='Meat',        id=9   -> 'mtx-0009'
        category='Oil',         id=7   -> 'olx-0007'
    """
    name = category_name.lower()
    first = name[0] if name else 'x'
    consonants = [ch for ch in name[1:] if ch.isalpha() and ch not in VOWELS]
    rest = ''.join(consonants[:2])
    prefix = (first + rest).ljust(3, 'x')
    return f'{prefix}-{product_id:04d}'


def _parse_decimal(value):
    if not value or not str(value).strip():
        return Decimal("0")
    return Decimal(str(value).strip())
