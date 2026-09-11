"""
Receipt formatting for thermal (ESC/POS) printers.

Builds plain-text receipt lines sent to core.tasks.async_print_receipt,
which streams them to the thermal printer over TCP/IP.
"""

from django.utils import timezone

from core.models import BusinessInfo

COL_WIDTH = 40


def _center(text, width=COL_WIDTH):
    text = str(text)
    if len(text) >= width:
        return text[:width]
    pad = width - len(text)
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def _truncate(text, width):
    text = str(text)
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def _fmt_money(value):
    return f"{value:,.2f}"


def _fmt_qty(value):
    value = value.normalize()
    if value == value.to_integral():
        return f"{value:f}"
    return f"{value:.2f}"


def build_receipt_lines(txn):
    """Return a list of plain-text lines describing a transaction."""
    biz = BusinessInfo.objects.first()
    business_name = biz.business_name if biz else "EIXN"
    phone = f"Tel {biz.contact_phone}" if biz and biz.contact_phone else None

    is_refund = txn.total_amount < 0

    lines = [
        "=" * COL_WIDTH,
        _center(business_name),
    ]
    if phone:
        lines.append(_center(phone))
    lines += [
        "=" * COL_WIDTH,
        f"{'REFUND' if is_refund else 'SALE'} # {txn.id}",
        f"Date: {timezone.localtime(txn.transaction_date):%Y-%m-%d %H:%M}",
        f"Cashier: {txn.cashier.get_full_name() or txn.cashier.username}",
    ]
    if txn.customer:
        lines.append(f"Customer: {_truncate(txn.customer.name, 34)}")

    lines.append("-" * COL_WIDTH)

    for item in txn.items.select_related('product').all():
        item_name = _truncate(item.product.name if item.product else 'Item', 22)
        qty = _fmt_qty(item.quantity_sold)
        unit = _fmt_money(item.price_at_sale)
        line_total = _fmt_money(item.quantity_sold * item.price_at_sale)
        lines.append(f"{item_name:<22} {qty:>4}  {unit:>9}")
        lines.append(f"{'':<31}{line_total:>9}")

    lines.append("-" * COL_WIDTH)

    if is_refund:
        lines.append(f"{'REFUND':<31}{_fmt_money(txn.total_amount):>9}")
        lines.append(f"{'TAKEN FROM':<31}{_fmt_money(txn.payment_amount):>9}")
    else:
        lines.append(f"{'TOTAL':<31}{_fmt_money(txn.total_amount):>9}")
        if txn.payment_amount:
            lines.append(f"{'PAID':<31}{_fmt_money(txn.payment_amount):>9}")
            change = txn.payment_amount - txn.total_amount
            if change > 0:
                lines.append(f"{'CHANGE':<31}{_fmt_money(change):>9}")
    lines.append(f"Payment: {txn.get_payment_type_display()}")

    lines += [
        "=" * COL_WIDTH,
        _center("THANK YOU"),
        _center("PLEASE KEEP THIS RECEIPT"),
    ]
    return lines