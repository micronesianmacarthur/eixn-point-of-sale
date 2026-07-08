import json
from datetime import date, timedelta
from decimal import Decimal

from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
from django.db.models import Count, F, Sum, Q
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from .decorators import require_open_session

from customers.models import Customer
from inventory.models import Bundle, Product
from .analytics import (
    get_customer_debt_ranking,
    get_daily_trend,
    get_payment_type_breakdown,
    get_sales_by_clerk,
    get_session_pnl,
    get_top_products,
    get_weekly_comparison,
)
from .cash_count import CURRENCY_DEFS, calculate_totals, calculate_removal
from .models import Session, Transaction, TransactionLineItem
from .services import batch_offline_recovery, close_session, process_checkout, process_return, void_transaction


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'sales/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = date.today()
        month_start = today.replace(day=1)
        txns_today = Transaction.objects.filter(transaction_date__date=today)
        context['sales_today_total'] = txns_today.aggregate(total=Sum('total_amount'))['total'] or 0
        context['sales_today_count'] = txns_today.count()
        top_item = (
            TransactionLineItem.objects.filter(transaction__transaction_date__date=today)
            .values('product__name')
            .annotate(total_qty=Sum('quantity_sold'))
            .order_by('-total_qty').first()
        )
        context['top_product'] = top_item
        context['chart_labels'], context['chart_data'] = get_daily_trend(days=30)
        context['low_stock_products'] = Product.objects.filter(stock_quantity__lte=F('min_stock_level'))
        context['payment_breakdown'] = get_payment_type_breakdown(today, today)
        context['sales_by_clerk'] = get_sales_by_clerk(today, today)
        context['weekly_comparison'] = get_weekly_comparison()
        context['monthly_total'] = Transaction.objects.filter(
            transaction_date__date__gte=month_start,
            transaction_date__date__lte=today,
        ).exclude(status=Transaction.Status.VOIDED).aggregate(total=Sum('total_amount'))['total'] or 0
        context['customer_debt_ranking'] = get_customer_debt_ranking(limit=10)
        context['backup_status'] = _read_backup_status()
        return context


class SessionCreateView(LoginRequiredMixin, CreateView):
    model = Session
    fields = ['starting_cash']

    def get_success_url(self):
        return self.request.META.get('HTTP_REFERER', reverse_lazy('sales:sale_list'))

    def form_valid(self, form):
        form.instance.opened_by = self.request.user
        messages.success(self.request, 'Session opened.')
        return super().form_valid(form)


class SessionCloseView(LoginRequiredMixin, UpdateView):
    model = Session
    template_name = 'sales/session_close.html'
    fields = ['ending_cash_actual']
    success_url = reverse_lazy('sales:dashboard')

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pnl = get_session_pnl(self.object.pk)
        context['pnl'] = pnl
        context['expected_cash'] = self.object.starting_cash + pnl['total_revenue']
        return context

    def form_valid(self, form):
        result = close_session(session_id=self.object.pk, actual_cash=form.cleaned_data['ending_cash_actual'], closed_by_user=self.request.user)
        if result['variance'] != 0:
            messages.warning(self.request, f'Session closed with cash variance: expected ${result["expected_cash"]:.2f}, actual ${result["actual_cash"]:.2f} ({"over" if result["variance"] < 0 else "short"} by ${abs(result["variance"]):.2f}).')
        messages.success(self.request, 'Session closed and posted.')
        return HttpResponseRedirect(self.get_success_url())


SESSION_COUNT_KEY = 'session_cash_counts'
SESSION_FINAL_KEY = 'session_close_final'


class StepCountView(LoginRequiredMixin, DetailView):
    model = Session
    template_name = 'sales/close/step1_count.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['currency_defs'] = CURRENCY_DEFS
        saved = self.request.session.get(SESSION_COUNT_KEY, {})
        counts = saved.get(str(self.object.pk), {})
        context['saved_counts'] = counts
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        counts = {}
        for _, key, _ in CURRENCY_DEFS:
            raw = request.POST.get(f'count_{key}', '0')
            try:
                counts[key] = max(0, int(raw))
            except (ValueError, TypeError):
                counts[key] = 0

        totals = calculate_totals(counts)

        if totals['grand_total'] < session.starting_cash:
            messages.error(request, 'Drawer total cannot be less than starting cash.')
            if SESSION_COUNT_KEY not in request.session:
                request.session[SESSION_COUNT_KEY] = {}
            request.session[SESSION_COUNT_KEY][str(session.pk)] = counts
            request.session.modified = True
            return redirect('sales:close_step1', pk=session.pk)

        if SESSION_COUNT_KEY not in request.session:
            request.session[SESSION_COUNT_KEY] = {}
        request.session[SESSION_COUNT_KEY][str(session.pk)] = counts
        request.session.modified = True

        return redirect('sales:close_step2', pk=session.pk)


class StepRemoveView(LoginRequiredMixin, DetailView):
    model = Session
    template_name = 'sales/close/step2_remove.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = self.request.session.get(SESSION_COUNT_KEY, {}).get(str(self.object.pk))
        if not counts:
            return redirect('sales:close_step1', pk=self.object.pk)

        totals = calculate_totals(counts)
        remove_amount = totals['grand_total'] - self.object.starting_cash
        removal = calculate_removal(remove_amount, counts) if remove_amount > 0 else None

        context.update({
            'currency_defs': CURRENCY_DEFS,
            'counts': counts,
            'totals': totals,
            'remove_amount': remove_amount,
            'removal': removal,
            'starting_cash': self.object.starting_cash,
        })
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        counts = request.session.get(SESSION_COUNT_KEY, {}).get(str(session.pk))
        if not counts:
            messages.error(request, 'Session expired. Please re-enter counts.')
            return redirect('sales:close_step1', pk=session.pk)

        action = request.POST.get('action')
        if action == 'back':
            return redirect('sales:close_step1', pk=session.pk)

        totals = calculate_totals(counts)
        if SESSION_FINAL_KEY not in request.session:
            request.session[SESSION_FINAL_KEY] = {}
        request.session[SESSION_FINAL_KEY][str(session.pk)] = {
            'counts': counts,
            'grand_total': str(totals['grand_total']),
            'starting_cash': str(session.starting_cash),
        }
        request.session.modified = True

        return redirect('sales:close_step3', pk=session.pk)


class StepReviewView(LoginRequiredMixin, DetailView):
    model = Session
    template_name = 'sales/close/step3_review.html'

    def get_queryset(self):
        return Session.objects.filter(status=Session.Status.OPEN)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pnl = get_session_pnl(self.object.pk)
        context['pnl'] = pnl
        context['expected_cash'] = self.object.starting_cash + pnl['total_revenue']
        context['currency_defs'] = CURRENCY_DEFS

        final = self.request.session.get(SESSION_FINAL_KEY, {}).get(str(self.object.pk))
        if final:
            context['grand_total'] = Decimal(final['grand_total'])
            context['counts'] = final['counts']
            context['starting_cash'] = Decimal(final['starting_cash'])
            totals = calculate_totals(final['counts'])
            context['totals'] = totals
            context['variance'] = Decimal(final['grand_total']) - context['expected_cash']
            remove_amount = totals['grand_total'] - Decimal(final['starting_cash'])
            context['remove_amount'] = remove_amount
            if remove_amount > 0:
                context['removal'] = calculate_removal(remove_amount, final['counts'])
            removal = context.get('removal')
            if removal:
                context['variance'] = Decimal(final['grand_total']) - context['expected_cash']
        return context

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk, status=Session.Status.OPEN)
        action = request.POST.get('action')

        if action == 'back':
            return redirect('sales:close_step2', pk=session.pk)

        if action == 'post':
            final = request.session.get(SESSION_FINAL_KEY, {}).get(str(session.pk))
            if not final:
                messages.error(request, 'Session data expired. Please start over.')
                return redirect('sales:close_step1', pk=session.pk)

            actual_cash = Decimal(final['grand_total'])

            result = close_session(
                session_id=session.pk,
                actual_cash=actual_cash,
                closed_by_user=request.user,
            )

            session.cash_count_breakdown = final['counts']
            session.save(update_fields=['cash_count_breakdown'])

            self._cleanup(request, session.pk)

            if result['variance'] != 0:
                messages.warning(request,
                    f'Session closed with cash variance: expected ${result["expected_cash"]:.2f}, '
                    f'actual ${result["actual_cash"]:.2f} ({"over" if result["variance"] < 0 else "short"} '
                    f'by ${abs(result["variance"]):.2f}).')
            messages.success(request, 'Session closed and posted.')
            return redirect('sales:dashboard')

        return redirect('sales:close_step3', pk=session.pk)

    @staticmethod
    def _cleanup(request, session_pk):
        if SESSION_COUNT_KEY in request.session:
            request.session[SESSION_COUNT_KEY].pop(str(session_pk), None)
        if SESSION_FINAL_KEY in request.session:
            request.session[SESSION_FINAL_KEY].pop(str(session_pk), None)
        request.session.modified = True


class ZReportPDFView(LoginRequiredMixin, View):
    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        pnl = get_session_pnl(session.pk)
        final = request.session.get(SESSION_FINAL_KEY, {}).get(str(session.pk), {})
        if not final:
            messages.error(request, 'Session data not found.')
            return redirect('sales:dashboard')

        totals = calculate_totals(final['counts'])
        variance = Decimal(final['grand_total']) - (session.starting_cash + pnl['total_revenue'])
        remove_amount = totals['grand_total'] - Decimal(final['starting_cash'])

        context = {
            'session': session,
            'pnl': pnl,
            'expected_cash': session.starting_cash + pnl['total_revenue'],
            'currency_defs': CURRENCY_DEFS,
            'grand_total': Decimal(final['grand_total']),
            'counts': final['counts'],
            'starting_cash': Decimal(final['starting_cash']),
            'totals': totals,
            'variance': variance,
            'remove_amount': remove_amount,
        }
        if remove_amount > 0:
            context['removal'] = calculate_removal(remove_amount, final['counts'])

        html = render_to_string('sales/close/step3_review_pdf.html', context, request=request)

        from weasyprint import HTML
        pdf = HTML(string=html).write_pdf()

        return HttpResponse(pdf, content_type='application/pdf',
                            headers={'Content-Disposition': f'attachment; filename="zreport-session-{session.pk}.pdf"'})


class SaleListView(LoginRequiredMixin, ListView):
    model = Transaction
    template_name = 'sales/sale_list.html'
    context_object_name = 'sales'
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Transaction.objects.select_related('session', 'customer', 'cashier').all()
        date_from = self.request.GET.get('date_from', '').strip()
        date_to = self.request.GET.get('date_to', '').strip()
        if date_from:
            qs = qs.filter(transaction_date__date__gte=date_from)
        if date_to:
            qs = qs.filter(transaction_date__date__lte=date_to)
        customer = self.request.GET.get('customer', '').strip()
        if customer:
            qs = qs.filter(customer__name__icontains=customer)
        amount_min = self.request.GET.get('amount_min', '').strip()
        amount_max = self.request.GET.get('amount_max', '').strip()
        if amount_min:
            qs = qs.filter(total_amount__gte=amount_min)
        if amount_max:
            qs = qs.filter(total_amount__lte=amount_max)
        cashier_id = self.request.GET.get('cashier', '').strip()
        if cashier_id:
            qs = qs.filter(cashier_id=cashier_id)
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_date_from'] = self.request.GET.get('date_from', '')
        context['current_date_to'] = self.request.GET.get('date_to', '')
        context['current_customer'] = self.request.GET.get('customer', '')
        context['current_amount_min'] = self.request.GET.get('amount_min', '')
        context['current_amount_max'] = self.request.GET.get('amount_max', '')
        context['current_cashier'] = self.request.GET.get('cashier', '')
        context['cashiers'] = get_user_model().objects.filter(is_active=True).order_by('username')
        return context


class SaleListTableView(LoginRequiredMixin, View):
    def get(self, request):
        qs = Transaction.objects.select_related('session', 'customer', 'cashier').all()
        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()
        if date_from:
            qs = qs.filter(transaction_date__date__gte=date_from)
        if date_to:
            qs = qs.filter(transaction_date__date__lte=date_to)
        customer = request.GET.get('customer', '').strip()
        if customer:
            qs = qs.filter(customer__name__icontains=customer)
        amount_min = request.GET.get('amount_min', '').strip()
        amount_max = request.GET.get('amount_max', '').strip()
        if amount_min:
            qs = qs.filter(total_amount__gte=amount_min)
        if amount_max:
            qs = qs.filter(total_amount__lte=amount_max)
        cashier_id = request.GET.get('cashier', '').strip()
        if cashier_id:
            qs = qs.filter(cashier_id=cashier_id)
        qs = qs.order_by('-created_at')[:100]
        return render(request, 'sales/partials/sale_table.html', {'sales': qs})


class CheckoutView(LoginRequiredMixin, TemplateView):
    template_name = 'sales/checkout.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['customers'] = Customer.objects.all()
        context['customers_json'] = list(Customer.objects.values('id', 'name', 'phone', 'credit_limit', 'cached_balance', 'is_owner'))
        context['cart'] = self.request.session.get('cart', [])
        context['service_products'] = Product.objects.filter(is_service=True).order_by('name')[:20]
        bundles = Bundle.objects.filter(is_active=True).prefetch_related('items__product')
        bundles_data = []
        for b in bundles:
            items_data = []
            total_normal = Decimal('0')
            for bi in b.items.all():
                p = bi.product
                normal_price = p.discount_price if p.is_on_sale and p.discount_price is not None else p.retail_price
                total_normal += normal_price * bi.quantity
                items_data.append({
                    'product_id': p.id,
                    'product_name': p.name,
                    'sku': p.sku,
                    'quantity': float(bi.quantity),
                    'normal_price': float(normal_price),
                    'is_variable_weight': p.is_variable_weight,
                    'is_service': p.is_service,
                    'stock': float(p.stock_quantity),
                })
            for item in items_data:
                item['price'] = item['normal_price']
            bundles_data.append({
                'id': b.id,
                'name': b.name,
                'item_count': len(items_data),
                'total_normal': float(total_normal),
                'items': items_data,
            })
        context['bundles'] = bundles_data
        context['bundles_json'] = bundles_data
        context['return_txn_id'] = None
        context['return_items'] = []
        return_txn_id = self.request.GET.get('return')
        if return_txn_id:
            try:
                txn = Transaction.objects.get(id=return_txn_id, status=Transaction.Status.POSTED)
                context['return_txn_id'] = txn.id
                context['return_txn_ref'] = f'#{txn.id}'
                items = []
                for li in txn.items.select_related('product').all():
                    p = li.product
                    items.append({
                        'product_id': p.id,
                        'product_name': p.name,
                        'sku': p.sku,
                        'price': float(li.price_at_sale),
                        'quantity': float(li.quantity_sold),
                        'stock': 999999,
                        'is_variable_weight': p.is_variable_weight,
                        'is_service': p.is_service,
                        'cost_price': float(li.cost_price),
                        'price_charged': float(li.price_at_sale),
                    })
                context['return_items'] = items
                context['return_payment_type'] = txn.payment_type
                context['return_customer_id'] = txn.customer_id or ''
            except Transaction.DoesNotExist:
                pass
        return context


class ProductSearchView(LoginRequiredMixin, View):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        products = Product.objects.filter(
            Q(sku__icontains=q) | Q(name__icontains=q),
            Q(is_service=True) | Q(stock_quantity__gt=0),
        )[:10] if q else []
        html = render_to_string('sales/partials/product_results.html', {'products': products, 'q': q}, request=request)
        return HttpResponse(html)


@method_decorator(require_open_session, name='dispatch')
class CartAddView(LoginRequiredMixin, View):
    def post(self, request):
        product_id = request.POST.get('product_id')
        product = get_object_or_404(Product, id=product_id)
        cart = request.session.get('cart', [])
        for item in cart:
            if item['product_id'] == product.id:
                if product.is_service:
                    item['quantity'] += 1
                else:
                    item['quantity'] = min(item['quantity'] + 1, product.stock_quantity)
                break
        else:
            cart.append({'product_id': product.id, 'product_name': product.name, 'sku': product.sku, 'price': float(product.discount_price if product.is_on_sale and product.discount_price else product.retail_price), 'quantity': 1, 'stock': product.stock_quantity})
        request.session['cart'] = cart
        html = render_to_string('sales/partials/cart_summary.html', {'cart': cart, 'customers': Customer.objects.all()}, request=request)
        return HttpResponse(html)


@method_decorator(require_open_session, name='dispatch')
class CartRemoveView(LoginRequiredMixin, View):
    def post(self, request, product_id):
        cart = request.session.get('cart', [])
        request.session['cart'] = [i for i in cart if i['product_id'] != product_id]
        html = render_to_string('sales/partials/cart_summary.html', {'cart': request.session['cart'], 'customers': Customer.objects.all()}, request=request)
        return HttpResponse(html)


@method_decorator(require_open_session, name='dispatch')
class CartUpdateQtyView(LoginRequiredMixin, View):
    def post(self, request, product_id):
        qty = int(request.POST.get('quantity', 1))
        cart = request.session.get('cart', [])
        for item in cart:
            if item['product_id'] == product_id:
                item['quantity'] = max(1, min(qty, item['stock']))
                break
        request.session['cart'] = cart
        html = render_to_string('sales/partials/cart_summary.html', {'cart': cart, 'customers': Customer.objects.all()}, request=request)
        return HttpResponse(html)


class CheckoutCompleteView(LoginRequiredMixin, View):
    def post(self, request):
        cart_json = request.POST.get('cart_json')
        if cart_json:
            try:
                cart = json.loads(cart_json)
            except (json.JSONDecodeError, TypeError):
                messages.error(request, 'Invalid cart data.')
                return HttpResponseRedirect(reverse_lazy('sales:checkout'))
        else:
            cart = request.session.get('cart', [])
            request.session['cart'] = []
        if not cart:
            messages.error(request, 'Cart is empty.')
            return HttpResponseRedirect(reverse_lazy('sales:checkout'))
        customer_id = request.POST.get('customer_id')
        payment_type = request.POST.get('payment_type', 'CASH')
        return_of = request.POST.get('return_of')
        try:
            if return_of:
                return_items = [
                    {
                        'product_id': i['product_id'],
                        'quantity': i['quantity'],
                        'price_charged': Decimal(str(i.get('price_charged', i['price']))),
                        'cost_price': Decimal(str(i.get('cost_price', i['price']))),
                    }
                    for i in cart
                ]
                refund_amount = sum(Decimal(str(i['price'])) * Decimal(str(i['quantity'])) for i in cart)
                txn = process_return(
                    original_txn_id=int(return_of),
                    return_items=return_items,
                    refund_amount=refund_amount,
                    refund_type=payment_type,
                    operator_user=request.user,
                )
                messages.success(request, f'Return #{txn.id} for original transaction #{return_of}.')
            else:
                active_session = Session.objects.filter(status=Session.Status.OPEN).first()
                if not active_session:
                    messages.error(request, 'No active session.')
                    return HttpResponseRedirect(reverse_lazy('sales:checkout'))
                items = [{'product_id': i['product_id'], 'quantity': i['quantity']} for i in cart]
                payments = [{'amount': sum(Decimal(str(i['price'])) * i['quantity'] for i in cart), 'payment_type': payment_type}]
                txn = process_checkout(session_id=active_session.id, items=items, payments=payments, customer_id=customer_id or None, operator_user=request.user)
                messages.success(request, f'Transaction #{txn.id} completed.')
        except (ValueError, Transaction.DoesNotExist) as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse_lazy('sales:checkout'))

    def get(self, request):
        return self.post(request)


class TopProductsTodayView(LoginRequiredMixin, View):
    def get(self, request):
        today = date.today()
        products = get_top_products(today, today, limit=10)
        html = render_to_string('sales/partials/top_products.html', {'products': products}, request=request)
        return HttpResponse(html)


class CreditCheckView(LoginRequiredMixin, View):
    def get(self, request):
        customer_id = request.GET.get('customer_id')
        cart = request.session.get('cart', [])
        cart_total = sum(Decimal(str(i['price'])) * i['quantity'] for i in cart)
        if not customer_id:
            return HttpResponse('<span class="text-green-600 text-sm">No customer selected.</span>')
        customer = get_object_or_404(Customer, id=customer_id)
        payment_type = request.GET.get('payment_type', 'CASH')
        if payment_type != 'STORE_CREDIT':
            return HttpResponse('<span class="text-green-600 text-sm">Cash/Card selected &mdash; no limit check needed.</span>')
        projected = customer.cached_balance + cart_total
        available = customer.credit_limit - customer.cached_balance
        if customer.is_owner:
            return HttpResponse('<span class="text-green-600 text-sm">Owner &mdash; unlimited credit.</span>')
        if projected <= customer.credit_limit:
            return HttpResponse(f'<span class="text-green-600 text-sm">Available credit: ${available} | Projected: ${projected}</span>')
        return HttpResponse(f'<span class="text-red-600 text-sm font-semibold">Warning: Projected total (${projected}) exceeds credit limit (${customer.credit_limit})!</span>')


class TransactionDetailView(LoginRequiredMixin, DetailView):
    model = Transaction
    template_name = 'sales/transaction_detail.html'
    context_object_name = 'txn'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['line_items'] = self.object.items.select_related('product').all()
        return context


class VoidSaleView(LoginRequiredMixin, View):
    def post(self, request, pk=None):
        pk = pk or request.POST.get('pk')
        try:
            void_transaction(txn_id=pk, operator_user=request.user)
            messages.success(request, f'Transaction #{pk} voided.')
        except ValueError as e:
            messages.error(request, str(e))
        if request.headers.get('HX-Request'):
            return render(request, 'sales/partials/sale_list_rows.html', {'sales': Transaction.objects.all().order_by('-created_at')[:50]})
        return HttpResponseRedirect(reverse_lazy('sales:sale_list'))


class ReturnSaleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            original = get_object_or_404(Transaction, id=pk)
            if original.status != Transaction.Status.POSTED:
                messages.error(request, 'Can only return a posted transaction.')
                return HttpResponseRedirect(reverse_lazy('sales:sale_list'))
            return_items = [
                {
                    'product_id': item.product_id,
                    'quantity': item.quantity_sold,
                    'price_charged': item.price_at_sale,
                    'cost_price': item.cost_price,
                }
                for item in original.items.all()
            ]
            refund_amount = original.total_amount
            txn = process_return(
                original_txn_id=pk,
                return_items=return_items,
                refund_amount=refund_amount,
                refund_type=original.payment_type,
                operator_user=request.user,
            )
            messages.success(request, f'Return #{txn.id} created for original transaction #{pk}.')
        except ValueError as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse_lazy('sales:sale_list'))


class OfflineRecoveryView(LoginRequiredMixin, TemplateView):
    template_name = 'sales/offline_recovery.html'

    def post(self, request):
        try:
            data = json.loads(request.body or '{}')
            rows = data.get('rows', [])
            if not rows:
                messages.error(request, 'No rows provided.')
                return HttpResponseRedirect(reverse_lazy('sales:offline_recovery'))
            session = batch_offline_recovery(rows=rows, operator_user=request.user)
            messages.success(request, f'{len(rows)} transaction(s) recovered in Virtual Session #{session.id}.')
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse_lazy('sales:offline_recovery'))


def _read_backup_status():
    """Read the last_backup.txt marker file and return a dict or None."""
    import os
    marker = os.path.join(settings.BASE_DIR, 'last_backup.txt')
    if os.path.exists(marker):
        try:
            with open(marker) as f:
                ts = f.read().strip()
            return {'last_sync': ts, 'status': 'OK'}
        except Exception:
            return None
    return None


class BackupTriggerView(LoginRequiredMixin, View):
    """Trigger a cloud backup (sync) and return updated backup status HTML."""

    def post(self, request):
        from django.core.management import call_command
        try:
            call_command('cloud_backup', no_upload=True)
            messages.success(request, 'Backup completed.')
        except Exception as e:
            messages.error(request, f'Backup failed: {e}')
        status = _read_backup_status()
        html = render_to_string('sales/partials/backup_status.html', {'backup_status': status}, request=request)
        return HttpResponse(html)
