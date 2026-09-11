from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce

from customers.models import Customer
from inventory.models import Product

from .models import Session, Transaction, TransactionLineItem


def get_daily_sales_stats(start_date, end_date):
    qs = Transaction.objects.filter(
        transaction_date__date__gte=start_date,
        transaction_date__date__lte=end_date,
    ).exclude(status=Transaction.Status.VOIDED)
    stats = qs.aggregate(
        total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
        count=Count('id'),
    )
    stats['average'] = stats['total'] / stats['count'] if stats['count'] else 0
    return stats


def get_sales_by_clerk(start_date, end_date, limit=10):
    return (
        Transaction.objects.filter(
            transaction_date__date__gte=start_date,
            transaction_date__date__lte=end_date,
        )
        .exclude(status=Transaction.Status.VOIDED)
        .values(cashier_username=F('cashier__username'))
        .annotate(
            total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
            count=Count('id'),
        )
        .order_by('-total')[:limit]
    )


def get_top_products(start_date=None, end_date=None, limit=10):
    filters = {"transaction__status__in": [Transaction.Status.POSTED]}
    if start_date:
        filters["transaction__transaction_date__date__gte"] = start_date
    if end_date:
        filters["transaction__transaction_date__date__lte"] = end_date
    return (
        TransactionLineItem.objects.filter(**filters)
        .values('product__name', 'product__sku')
        .annotate(
            total_qty=Sum('quantity_sold'),
            total_revenue=Coalesce(
                Sum(F('quantity_sold') * F('price_at_sale')),
                Value(0, output_field=DecimalField()),
            ),
        )
        .order_by('-total_qty')[:limit]
    )


def get_payment_type_breakdown(start_date, end_date):
    qs = (
        Transaction.objects.filter(
            transaction_date__date__gte=start_date,
            transaction_date__date__lte=end_date,
        )
        .exclude(status=Transaction.Status.VOIDED)
        .values('payment_type')
        .annotate(
            total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
            count=Count('id'),
        )
        .order_by('-total')
    )
    result = {item['payment_type']: {'total': item['total'], 'count': item['count']} for item in qs}
    for pt in [Transaction.PaymentType.CASH, Transaction.PaymentType.CARD,
               Transaction.PaymentType.STORE_CREDIT, Transaction.PaymentType.OWNER_DRAW]:
        if pt.value not in result:
            result[pt.value] = {'total': 0, 'count': 0}
    return result


def get_daily_trend(days=30):
    today = date.today()
    labels, data = [], []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime('%b %d'))
        day_total = (
            Transaction.objects.filter(transaction_date__date=d)
            .exclude(status=Transaction.Status.VOIDED)
            .aggregate(total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())))['total']
        )
        data.append(float(day_total))
    return labels, data


def get_session_pnl(session_id):
    session = Session.objects.get(id=session_id)
    txns = session.transactions.exclude(status=Transaction.Status.VOIDED)
    total_revenue = txns.aggregate(
        total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField()))
    )['total']
    total_cost = (
        TransactionLineItem.objects.filter(transaction__session=session)
        .exclude(transaction__status=Transaction.Status.VOIDED)
        .aggregate(
            total=Coalesce(
                Sum(F('quantity_sold') * F('cost_price')),
                Value(0, output_field=DecimalField()),
            )
        )['total']
    )
    gross_profit = total_revenue - total_cost
    payment_breakdown = get_payment_type_breakdown(
        session.start_time.date(),
        (session.end_time or session.start_time).date(),
    )
    txn_count = txns.count()
    return {
        'session': session,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'gross_profit': gross_profit,
        'margin': (gross_profit / total_revenue * 100) if total_revenue else 0,
        'sale_count': txn_count,
        'average_ticket': total_revenue / txn_count if txn_count else 0,
        'payment_breakdown': payment_breakdown,
    }


def get_customer_debt_ranking(limit=20):
    return (
        Customer.objects.filter(cached_balance__gt=0)
        .order_by('-cached_balance')[:limit]
        .values('name', 'cached_balance', 'credit_limit')
    )


def get_weekly_comparison():
    today = date.today()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)

    this_week = Transaction.objects.filter(
        transaction_date__date__gte=this_week_start,
        transaction_date__date__lte=today,
    ).exclude(status=Transaction.Status.VOIDED).aggregate(
        total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
        count=Count('id'),
    )
    last_week = Transaction.objects.filter(
        transaction_date__date__gte=last_week_start,
        transaction_date__date__lt=this_week_start,
    ).exclude(status=Transaction.Status.VOIDED).aggregate(
        total=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
        count=Count('id'),
    )

    return {'this_week': this_week, 'last_week': last_week}
