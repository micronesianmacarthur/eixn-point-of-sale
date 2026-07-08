from decimal import Decimal
from django import template

register = template.Library()


@register.filter
def multiply(value, arg):
    return Decimal(str(value)) * Decimal(str(arg))


@register.filter
def sum_cart(cart):
    return sum(Decimal(str(i['price'])) * i['quantity'] for i in cart)


@register.filter
def cart_qty(cart):
    return sum(i['quantity'] for i in cart)


@register.filter
def get_item(d, key):
    return d.get(key)
