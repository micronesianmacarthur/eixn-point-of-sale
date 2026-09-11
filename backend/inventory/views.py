import csv
import re
from decimal import ROUND_HALF_UP, Decimal
from core.models import SystemSetting
import io

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, ExpressionWrapper, F, Q, Sum
from django.db.models import DecimalField as DecimalModelField
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView, View
from django.views.decorators.http import require_POST

from django import forms
from customers.models import Customer
from sales.models import Session, TransactionLineItem
from .models import Bundle, BundleItem, Category, InventoryAdjustment, InventoryReceipt, InventoryReceiptItem, InventoryStockCount, Product, PurchaseOrder, PurchaseOrderItem, RecipeIngredient, Vendor
from .services import bulk_seed_products_csv, execute_repack, generate_sku, post_stock_count, receive_inventory


class ManagerOrAdminMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_manager or user.is_admin)


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'inventory/product_list.html'
    context_object_name = 'products'
    ordering = ['name']
    paginate_by = 50

    def get_queryset(self):
        qs = Product.objects.select_related('vendor', 'category')
        vendor = self.request.GET.get('vendor')
        category = self.request.GET.get('category')
        q = self.request.GET.get('q', '').strip()
        low_stock = self.request.GET.get('low_stock')

        if vendor:
            qs = qs.filter(vendor_id=vendor)
        if category:
            qs = qs.filter(category_id=category)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
        if low_stock:
            qs = qs.exclude(vendor__name__iexact='N/A SERVICE').exclude(is_service=True).exclude(is_variable_weight=True).filter(stock_quantity__lte=F('min_stock_level'))

        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vendor_list'] = Vendor.objects.exclude(name__iexact='N/A SERVICE')
        context['category_list'] = Category.objects.all()
        context['current_vendor'] = self.request.GET.get('vendor', '')
        context['current_category'] = self.request.GET.get('category', '')
        context['current_q'] = self.request.GET.get('q', '')
        context['current_low_stock'] = self.request.GET.get('low_stock', '')
        return context


class ProductListTableView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'inventory/partials/product_table.html'
    context_object_name = 'products'
    paginate_by = 50

    def get_queryset(self):
        qs = Product.objects.select_related('vendor', 'category')
        vendor = self.request.GET.get('vendor')
        category = self.request.GET.get('category')
        q = self.request.GET.get('q', '').strip()
        low_stock = self.request.GET.get('low_stock')

        if vendor:
            qs = qs.filter(vendor_id=vendor)
        if category:
            qs = qs.filter(category_id=category)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
        if low_stock:
            qs = qs.exclude(vendor__name__iexact='N/A SERVICE').exclude(is_service=True).exclude(is_variable_weight=True).filter(stock_quantity__lte=F('min_stock_level'))

        return qs.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_vendor'] = self.request.GET.get('vendor', '')
        context['current_category'] = self.request.GET.get('category', '')
        context['current_q'] = self.request.GET.get('q', '')
        context['current_low_stock'] = self.request.GET.get('low_stock', '')
        return context


def _report_products(vendor, category, q):
    qs = Product.objects.select_related('vendor', 'category') \
        .exclude(vendor__name__iexact='N/A SERVICE') \
        .exclude(is_service=True) \
        .exclude(is_variable_weight=True)
    if vendor:
        qs = qs.filter(vendor_id=vendor)
    if category:
        qs = qs.filter(category_id=category)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    return qs.order_by('category__name', 'name')


class InventoryReportView(LoginRequiredMixin, TemplateView):
    template_name = 'inventory/inventory_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        price_type = self.request.GET.get('price', 'retail')
        price_type = price_type if price_type in ('retail', 'cost') else 'retail'
        unit_attr = 'retail_price' if price_type == 'retail' else 'cost_price'

        rows = []
        total_value = Decimal('0')
        for p in _report_products(
            self.request.GET.get('vendor'),
            self.request.GET.get('category'),
            self.request.GET.get('q', '').strip(),
        ):
            unit = getattr(p, unit_attr)
            line_total = (p.stock_quantity * unit).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_value += line_total
            rows.append({'product': p, 'unit_price': unit, 'line_total': line_total})

        context['rows'] = rows
        context['total_value'] = total_value
        context['price_type'] = price_type
        context['unit_label'] = 'Retail' if price_type == 'retail' else 'Cost'
        context['vendor_list'] = Vendor.objects.exclude(name__iexact='N/A SERVICE')
        context['category_list'] = Category.objects.all()
        context['current_vendor'] = self.request.GET.get('vendor', '')
        context['current_category'] = self.request.GET.get('category', '')
        context['current_q'] = self.request.GET.get('q', '')
        context['current_vendor_name'] = Vendor.objects.get(id=context['current_vendor']).name if context['current_vendor'] else ''
        context['current_category_name'] = Category.objects.get(id=context['current_category']).name if context['current_category'] else ''
        context['filter_query'] = self.request.GET.urlencode()
        return context


def _parse_count_rows(product_ids, post):
    products = {
        p.id: p for p in Product.objects.select_related('vendor', 'category').filter(id__in=product_ids)
    }
    rows = []
    for pid in product_ids:
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        product = products.get(pid_int)
        if not product:
            continue
        raw = post.get(f'qty_{pid_int}', '').strip()
        reason = post.get(f'reason_{pid_int}', '') or InventoryAdjustment.Reason.PHYSICAL_COUNT
        counted = None
        error = None
        if raw:
            try:
                counted = Decimal(raw)
                if counted < 0:
                    error = 'Quantity cannot be negative.'
            except Exception:
                error = f'Invalid quantity "{raw}".'
        rows.append({'product': product, 'counted': counted, 'reason': reason, 'error': error})
    return rows


class InventoryCountEntryView(ManagerOrAdminMixin, TemplateView):
    template_name = 'inventory/count_entry.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reasons'] = InventoryAdjustment.Reason.choices
        context['preview_mode'] = self.request.method == 'POST'
        context['filter_query'] = self.request.GET.urlencode()
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        context['rows'] = [
            {'product': p, 'counted': None, 'reason': InventoryAdjustment.Reason.PHYSICAL_COUNT, 'error': None}
            for p in _report_products(
                request.GET.get('vendor'), request.GET.get('category'), request.GET.get('q', '').strip()
            )
        ]
        return render(request, self.template_name, context)

    def post(self, request):
        rows = _parse_count_rows(request.POST.getlist('product_id'), request.POST)
        preview_rows = []
        total_delta_cost = Decimal('0')
        for row in rows:
            if row['error'] or row['counted'] is None:
                continue
            previous = Decimal(str(row['product'].stock_quantity))
            if row['counted'] == previous:
                continue
            delta = row['counted'] - previous
            delta_cost = (delta * Decimal(str(row['product'].cost_price))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )
            total_delta_cost += delta_cost
            preview_rows.append({
                **row,
                'previous': previous,
                'delta': delta,
                'delta_cost': delta_cost,
                'reason_label': dict(InventoryAdjustment.Reason.choices).get(row['reason'], row['reason']),
            })

        context = self.get_context_data()
        context['rows'] = rows
        context['preview_rows'] = preview_rows
        context['total_delta_cost'] = total_delta_cost
        context['note'] = request.POST.get('note', '')
        context['errors'] = [r['error'] for r in rows if r['error']]
        if not preview_rows and not context['errors']:
            messages.info(request, 'No changes to preview — counts match system stock.')
        if context['errors']:
            messages.error(request, 'Fix the highlighted rows before posting.')
        return render(request, self.template_name, context)


class InventoryCountPostView(ManagerOrAdminMixin, View):
    def post(self, request):
        product_ids = request.POST.getlist('product_id')
        note = (request.POST.get('note', '') or '').strip()
        parsed = _parse_count_rows(product_ids, request.POST)

        errors = [r['error'] for r in parsed if r['error']]
        if errors:
            for err in errors:
                messages.error(request, err)
            return HttpResponseRedirect(reverse('inventory:count_entry'))

        items = [
            {'product_id': r['product'].id, 'counted_qty': r['counted'], 'reason': r['reason']}
            for r in parsed if r['counted'] is not None
        ]
        if not items:
            messages.info(request, 'No counts were entered.')
            return HttpResponseRedirect(reverse('inventory:count_entry'))

        try:
            count, adjustments = post_stock_count(items=items, adjusted_by=request.user, note=note)
        except ValueError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(reverse('inventory:count_entry'))

        if count is None:
            messages.info(request, 'No changes to post — counts match system stock.')
            return HttpResponseRedirect(reverse('inventory:count_entry'))

        messages.success(
            request,
            f'Stock count COUNT-{count.pk} posted with {len(adjustments)} adjustment(s).'
        )
        return HttpResponseRedirect(reverse('inventory:adjustment_list') + f'?count={count.pk}')


class InventoryAdjustmentListView(ManagerOrAdminMixin, ListView):
    model = InventoryAdjustment
    template_name = 'inventory/adjustment_list.html'
    context_object_name = 'adjustments'
    paginate_by = 50

    def get_queryset(self):
        qs = InventoryAdjustment.objects.select_related(
            'product', 'product__vendor', 'stock_count', 'adjusted_by'
        )
        count_id = self.request.GET.get('count')
        if count_id:
            qs = qs.filter(stock_count_id=count_id)
        return qs.order_by('-created_at', '-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        context['adjustment_count'] = qs.count()
        context['total_units'] = sum((a.delta for a in qs), Decimal('0'))
        context['total_cost'] = sum((a.delta_cost_value for a in qs), Decimal('0'))
        context['counts'] = InventoryStockCount.objects.order_by('-created_at')[:20]
        context['current_count'] = self.request.GET.get('count', '')
        return context


class ReceiveForm(forms.Form):
    vendor = forms.ModelChoiceField(queryset=Vendor.objects.exclude(name__iexact='N/A SERVICE'), required=False)
    purchase_order = forms.ModelChoiceField(
        queryset=PurchaseOrder.objects.filter(status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT]),
        required=False,
    )
    owner_contribution_amount = forms.DecimalField(required=False, min_value=0, decimal_places=2)
    receipt_number = forms.CharField(required=False, max_length=100)


class ReceiveProductsView(ManagerOrAdminMixin, FormView):
    template_name = 'inventory/receive_products.html'
    form_class = ReceiveForm
    success_url = reverse_lazy('inventory:receive_products')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vendor_list'] = Vendor.objects.exclude(name__iexact='N/A SERVICE')
        context['product_list'] = Product.objects.select_related('vendor').order_by('name')
        context['category_list'] = Category.objects.all()
        context['po_list'] = PurchaseOrder.objects.filter(
            status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT]
        ).select_related('vendor').order_by('-created_at')

        markup_setting = SystemSetting.objects.filter(key='DEFAULT_MARKUP_RATE').first()
        context['markup_rate'] = float(markup_setting.value) if markup_setting else 0.15

        po_id = self.request.GET.get('po_id')
        if po_id:
            po = get_object_or_404(PurchaseOrder, id=po_id)
            context['selected_po'] = po
            context['po_items'] = po.items.select_related('product').all()

        product_id = self.request.GET.get('product_id')
        if product_id and not po_id:
            product = get_object_or_404(Product, id=product_id)
            context['pre_selected_product'] = product

        return context

    def get_initial(self):
        initial = super().get_initial()
        po_id = self.request.GET.get('po_id')
        if po_id:
            po = get_object_or_404(PurchaseOrder, id=po_id)
            initial['vendor'] = po.vendor
            initial['purchase_order'] = po
        return initial

    def form_valid(self, form):
        active_session = Session.objects.filter(status=Session.Status.OPEN).first()
        if not active_session:
            messages.error(self.request, 'No active register session. Open one before receiving products.')
            return self.form_invalid(form)

        vendor = form.cleaned_data.get('vendor')
        po = form.cleaned_data.get('purchase_order')
        owner_contribution_amount = form.cleaned_data.get('owner_contribution_amount') or Decimal('0.00')
        receipt_number = form.cleaned_data.get('receipt_number', '')
        funded_by_owner = owner_contribution_amount > 0
        owner_customer = None
        if funded_by_owner:
            owner_customer = Customer.objects.filter(is_owner=True).first()

        row_ids = set()
        pattern = re.compile(r'^(?:product|new_name)_(\d+)$')
        for key in self.request.POST.keys():
            m = pattern.match(key)
            if m:
                row_ids.add(int(m.group(1)))

        if not row_ids:
            messages.error(self.request, 'Add at least one item.')
            return self.form_invalid(form)

        if not vendor:
            has_non_service = False
            for rid in sorted(row_ids):
                if has_non_service:
                    break
                new_name = self.request.POST.get(f'new_name_{rid}', '').strip()
                if not new_name:
                    existing_id = self.request.POST.get(f'product_{rid}')
                    if existing_id:
                        try:
                            p = Product.objects.get(id=int(existing_id))
                            if not p.is_service:
                                has_non_service = True
                        except Product.DoesNotExist:
                            pass
            if has_non_service:
                messages.error(self.request, 'Vendor is required for non-stock products.')
                return self.form_invalid(form)
            na_vendor, _ = Vendor.objects.get_or_create(name='N/A SERVICE')
            vendor = na_vendor

        items = []
        created_products = []
        for rid in sorted(row_ids):
            existing_id = self.request.POST.get(f'product_{rid}')
            new_name = self.request.POST.get(f'new_name_{rid}', '').strip()
            qty = _parse_decimal(self.request.POST.get(f'qty_{rid}', '0'))
            cost_price = _parse_decimal(self.request.POST.get(f'cost_price_{rid}', '0'))
            retail_price = _parse_decimal(self.request.POST.get(f'retail_price_{rid}', '0'))
            min_stock = _parse_decimal(self.request.POST.get(f'min_stock_{rid}', '0'))

            if new_name:
                is_service = self.request.POST.get(f'new_is_service_{rid}') == 'on'
            else:
                is_service = Product.objects.filter(id=int(existing_id), is_service=True).exists()

            if not new_name and qty <= 0 and not is_service:
                continue

            if new_name:
                category_id = self.request.POST.get(f'new_category_{rid}')
                is_variable_weight = self.request.POST.get(f'new_is_variable_weight_{rid}') == 'on'

                product = Product.objects.create(
                    vendor=vendor,
                    category_id=category_id or None,
                    name=new_name.upper(),
                    sku='',
                    cost_price=cost_price,
                    retail_price=retail_price,
                    min_stock_level=min_stock,
                    stock_quantity=0,
                    is_service=is_service,
                    is_variable_weight=is_variable_weight,
                )
                if product.category_id:
                    product.sku = generate_sku(product.category.name, product.id)
                else:
                    product.sku = generate_sku('GEN', product.id)
                product.save(update_fields=['sku'])
                product_id = product.id
                created_products.append(product)
            else:
                product_id = int(existing_id)
                Product.objects.filter(id=product_id).update(
                    vendor=vendor,
                    cost_price=cost_price,
                    retail_price=retail_price,
                    min_stock_level=min_stock,
                )

            items.append({
                'product_id': product_id,
                'quantity': qty,
                'cost_price': cost_price,
            })

        if not items:
            messages.error(self.request, 'Add at least one item with quantity > 0.')
            return self.form_invalid(form)

        receipt = receive_inventory(
            vendor=vendor,
            received_by=self.request.user,
            items=items,
            purchase_order=po,
            funded_by_owner=funded_by_owner,
            owner_contribution_amount=owner_contribution_amount,
            owner_customer_id=owner_customer.id if owner_customer else None,
            receipt_number=receipt_number,
            session=active_session,
            operator_user=self.request.user,
        )

        msg = f'Received {len(items)} product(s). Receipt #{receipt.id}.'
        if created_products:
            msg += f' Created {len(created_products)} new product(s).'
        messages.success(self.request, msg)
        return HttpResponseRedirect(self.success_url)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return self.render_to_response(self.get_context_data(form=form))


def _parse_decimal(value):
    if not value or not str(value).strip():
        return Decimal('0')
    try:
        return Decimal(str(value).strip())
    except Exception:
        return Decimal('0')


class ReceiveProductSearchView(LoginRequiredMixin, View):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        products = Product.objects.filter(
            Q(sku__icontains=q) | Q(name__icontains=q)
        ).select_related('vendor').order_by('name')[:15] if q else []
        html = render_to_string('inventory/partials/receive_product_search.html', {'products': products, 'q': q}, request=request)
        return HttpResponse(html)


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'inventory/product_detail.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.object
        context['sales'] = TransactionLineItem.objects.filter(
            product=product
        ).select_related('transaction__cashier', 'transaction__customer').order_by('-transaction__created_at')
        context['receipts'] = InventoryReceiptItem.objects.filter(
            product=product
        ).select_related('inventory_receipt__vendor', 'inventory_receipt__received_by').order_by('-inventory_receipt__received_at')
        context['vendor_list'] = Vendor.objects.exclude(name__iexact='N/A SERVICE')
        context['category_list'] = Category.objects.all()
        return context


class ProductUpdateView(ManagerOrAdminMixin, UpdateView):
    model = Product
    fields = ['name', 'category', 'vendor', 'retail_price', 'discount_price', 'is_on_sale', 'is_service', 'is_variable_weight', 'min_stock_level']
    template_name = 'inventory/product_list.html'
    success_url = reverse_lazy('inventory:product_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['vendor'].required = False
        return form

    def form_valid(self, form):
        product = form.save()
        messages.success(self.request, f'Product "{product.name}" updated.')
        return HttpResponseRedirect(self.success_url)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class ProductDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, id=pk)
        name = product.name
        if TransactionLineItem.objects.filter(product=product).exists():
            messages.error(
                request,
                f'Cannot delete "{name}" — it has been used in sales transactions.',
            )
            return HttpResponseRedirect(reverse_lazy('inventory:product_list'))

        try:
            product.delete()
        except ProtectedError:
            messages.error(
                request,
                f'Cannot delete "{name}" — it is linked to purchase orders, receipts, or recipes.',
            )
            return HttpResponseRedirect(reverse_lazy('inventory:product_list'))
        messages.success(request, f'Product "{name}" deleted.')
        return HttpResponseRedirect(reverse_lazy('inventory:product_list'))


class PurchaseOrderCreateView(ManagerOrAdminMixin, CreateView):
    model = PurchaseOrder
    fields = ['vendor']
    template_name = 'inventory/purchase_order_list.html'
    success_url = reverse_lazy('inventory:purchase_order_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Purchase Order #{form.instance.pk} created.')
        return super().form_valid(form)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class PurchaseOrderListView(LoginRequiredMixin, ListView):
    model = PurchaseOrder
    queryset = PurchaseOrder.objects.select_related('vendor', 'created_by').annotate(
        item_count=Count('items'),
        total_cost=Sum(
            ExpressionWrapper(
                F('items__quantity') * F('items__product__cost_price'),
                output_field=DecimalModelField(max_digits=14, decimal_places=2),
            )
        ),
    ).order_by('-created_at')
    template_name = 'inventory/purchase_order_list.html'
    context_object_name = 'orders'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vendor_list'] = Vendor.objects.exclude(name__iexact='N/A SERVICE')
        return context


class PurchaseOrderDetailView(LoginRequiredMixin, DetailView):
    model = PurchaseOrder
    template_name = 'inventory/purchase_order_detail.html'
    context_object_name = 'po'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        po = self.object
        items = po.items.select_related('product').all()
        line_items = []
        total = 0
        for item in items:
            line_total = item.quantity * item.product.cost_price
            total += line_total
            line_items.append({
                'id': item.id,
                'sku': item.product.sku,
                'name': item.product.name,
                'quantity': item.quantity,
                'unit_cost': item.product.cost_price,
                'line_total': line_total,
            })
        context['line_items'] = line_items
        context['total_cost'] = total
        context['receipts'] = po.receipts.select_related('received_by').prefetch_related('items__product').all()
        return context


VALID_PO_TRANSITIONS = {
    PurchaseOrder.Status.DRAFT: [PurchaseOrder.Status.SENT, PurchaseOrder.Status.CANCELLED],
    PurchaseOrder.Status.SENT: [PurchaseOrder.Status.CANCELLED],
}


class PurchaseOrderStatusView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        po = get_object_or_404(PurchaseOrder, id=pk)
        new_status = request.POST.get('status')
        if new_status not in PurchaseOrder.Status.values:
            messages.error(request, f'Invalid status "{new_status}".')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))
        allowed = VALID_PO_TRANSITIONS.get(po.status, [])
        if new_status not in allowed:
            messages.error(request, f'Cannot change status from {po.get_status_display()} to {dict(PurchaseOrder.Status.choices).get(new_status)}.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))
        po.status = new_status
        po.save(update_fields=['status'])
        messages.success(request, f'PO #{po.id} status changed to {po.get_status_display()}.')
        return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))


class PurchaseOrderItemUpdateView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        item = get_object_or_404(PurchaseOrderItem, id=pk)
        po = item.purchase_order
        if po.status != PurchaseOrder.Status.DRAFT:
            messages.error(request, 'Can only edit items on draft purchase orders.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))
        try:
            qty = int(request.POST.get('quantity', 0))
        except (ValueError, TypeError):
            messages.error(request, 'Invalid quantity.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))
        if qty < 0:
            messages.error(request, 'Quantity cannot be negative.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))
        if qty == 0:
            item.delete()
            messages.success(request, f'{item.product.name} removed from PO.')
        else:
            item.quantity = qty
            item.save(update_fields=['quantity'])
            messages.success(request, f'{item.product.name} quantity updated to {qty}.')
        return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))


class PurchaseOrderItemDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        item = get_object_or_404(PurchaseOrderItem, id=pk)
        po = item.purchase_order
        if po.status != PurchaseOrder.Status.DRAFT:
            messages.error(request, 'Can only remove items from draft purchase orders.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))
        name = item.product.name
        item.delete()
        messages.success(request, f'{name} removed from PO.')
        return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[po.pk]))


class PurchaseOrderAddItemView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        po = get_object_or_404(PurchaseOrder, id=pk)
        if po.status != PurchaseOrder.Status.DRAFT:
            messages.error(request, 'Can only add items to draft purchase orders.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))
        product_id = request.POST.get('product_id')
        if not product_id:
            messages.error(request, 'Select a product.')
            return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))
        try:
            qty = int(request.POST.get('quantity', 1))
        except (ValueError, TypeError):
            qty = 1
        if qty <= 0:
            qty = 1
        product = get_object_or_404(Product, id=product_id)
        item, created = PurchaseOrderItem.objects.get_or_create(
            purchase_order=po,
            product=product,
            defaults={'quantity': qty},
        )
        if not created:
            item.quantity += qty
            item.save(update_fields=['quantity'])
        messages.success(request, f'{product.name} added to PO.')
        return HttpResponseRedirect(reverse_lazy('inventory:purchase_order_detail', args=[pk]))


class PurchaseOrderProductSearchView(LoginRequiredMixin, View):
    def get(self, request, pk):
        q = request.GET.get('q', '').strip()
        po = get_object_or_404(PurchaseOrder, id=pk)
        existing_ids = po.items.values_list('product_id', flat=True)
        products = Product.objects.filter(
            Q(sku__icontains=q) | Q(name__icontains=q)
        ).exclude(id__in=existing_ids).select_related('vendor').order_by('name')[:15] if q else []
        html = render_to_string('inventory/partials/po_product_search.html', {
            'products': products, 'q': q, 'po': po,
        }, request=request)
        return HttpResponse(html)


class LowStockView(LoginRequiredMixin, View):
    def get(self, request):
        low_stock = Product.objects.exclude(vendor__name__iexact='N/A SERVICE').exclude(is_service=True).exclude(is_variable_weight=True).filter(stock_quantity__lte=F('min_stock_level')).select_related('vendor').order_by('vendor__name', 'name')

        child_ids = set(RecipeIngredient.objects.values_list('child_product_id', flat=True).distinct())
        vendor_products = []
        child_products = []
        for p in low_stock:
            (child_products if p.id in child_ids else vendor_products).append(p)

        vendors = {}
        for p in vendor_products:
            vendors.setdefault(p.vendor, []).append(p)

        recipes = RecipeIngredient.objects.filter(
            child_product_id__in=[p.id for p in child_products]
        ).select_related('parent_product', 'child_product')

        parent_children = {}
        for recipe in recipes:
            parent_children.setdefault(recipe.parent_product, []).append({
                'child': recipe.child_product,
                'qty_per_parent': recipe.quantity_required,
            })

        # Products already on a pending PO (DRAFT or SENT)
        low_stock_ids = [p.id for p in low_stock]
        pending_ids = set(PurchaseOrderItem.objects.filter(
            product_id__in=low_stock_ids,
            purchase_order__status__in=[PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.SENT],
        ).values_list('product_id', flat=True).distinct())

        # Existing draft POs per vendor
        vendor_ids = list(vendors.keys())
        draft_pos = {po.vendor_id: po.id for po in PurchaseOrder.objects.filter(
            vendor_id__in=[v.id for v in vendor_ids],
            status=PurchaseOrder.Status.DRAFT,
        )}

        html = render_to_string('inventory/partials/low_stock_list.html', {
            'vendors': vendors,
            'parent_children': parent_children,
            'total_products': Product.objects.count(),
            'pending_product_ids': pending_ids,
            'vendor_draft_pos': draft_pos,
        }, request=request)
        return HttpResponse(html)


class CreateDraftPOView(LoginRequiredMixin, View):
    def post(self, request):
        vendor_id = request.POST.get('vendor_id')
        product_ids = request.POST.getlist('product_ids')
        if not vendor_id or not product_ids:
            messages.error(request, 'Select a vendor and at least one product.')
            return HttpResponse(status=204)
        vendor = get_object_or_404(Vendor, id=vendor_id)

        po = PurchaseOrder.objects.filter(vendor=vendor, status=PurchaseOrder.Status.DRAFT).first()
        if po:
            created_new = False
        else:
            po = PurchaseOrder.objects.create(vendor=vendor, created_by=request.user, status=PurchaseOrder.Status.DRAFT)
            created_new = True

        for pid in product_ids:
            product = get_object_or_404(Product, id=pid)
            reorder_qty = max(product.min_stock_level * 2 - product.stock_quantity, 1)
            existing = PurchaseOrderItem.objects.filter(purchase_order=po, product=product).first()
            if existing:
                PurchaseOrderItem.objects.filter(pk=existing.pk).update(quantity=F('quantity') + reorder_qty)
            else:
                PurchaseOrderItem.objects.create(purchase_order=po, product=product, quantity=reorder_qty)

        if created_new:
            messages.success(request, f'Draft PO #{po.id} created for {vendor.name}.')
        else:
            messages.success(request, f'Items added to existing Draft PO #{po.id} for {vendor.name}.')
        return HttpResponse(status=204, headers={'HX-Refresh': 'true'})


class VendorListView(LoginRequiredMixin, ListView):
    model = Vendor
    queryset = Vendor.objects.exclude(name__iexact='N/A SERVICE')
    template_name = 'inventory/vendor_list.html'
    context_object_name = 'vendors'
    paginate_by = 25


class VendorCreateView(ManagerOrAdminMixin, CreateView):
    model = Vendor
    fields = ['name', 'contact_person', 'phone', 'email']
    template_name = 'inventory/vendor_list.html'
    success_url = reverse_lazy('inventory:vendor_list')

    def form_valid(self, form):
        form.instance.name = form.instance.name.upper()
        form.instance.contact_person = form.instance.contact_person.upper()
        result = super().form_valid(form)
        messages.success(self.request, f'Vendor "{form.instance.name}" created.')
        return result

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class VendorCreateQuickView(ManagerOrAdminMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Name is required.'}, status=400)
        name = name.upper()
        vendor = Vendor.objects.create(
            name=name,
            contact_person=request.POST.get('contact_person', '').upper(),
            phone=request.POST.get('phone', ''),
            email=request.POST.get('email', ''),
        )
        return JsonResponse({'id': vendor.id, 'name': vendor.name})


class VendorUpdateView(ManagerOrAdminMixin, UpdateView):
    model = Vendor
    fields = ['name', 'contact_person', 'phone', 'email']
    template_name = 'inventory/vendor_list.html'
    success_url = reverse_lazy('inventory:vendor_list')

    def form_valid(self, form):
        form.instance.name = form.instance.name.upper()
        form.instance.contact_person = form.instance.contact_person.upper()
        messages.success(self.request, f'Vendor "{form.instance.name}" updated.')
        return super().form_valid(form)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class VendorDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        vendor = get_object_or_404(Vendor, id=pk)
        name = vendor.name
        try:
            vendor.delete()
        except ProtectedError:
            messages.error(request, f'Cannot delete "{name}" — it has {vendor.products.count()} product(s) assigned.')
            return HttpResponseRedirect(reverse_lazy('inventory:vendor_list'))
        messages.success(request, f'Vendor "{name}" deleted.')
        return HttpResponseRedirect(reverse_lazy('inventory:vendor_list'))


class CategoryListView(ManagerOrAdminMixin, ListView):
    model = Category
    template_name = 'inventory/category_list.html'
    context_object_name = 'categories'
    ordering = 'name'


class CategoryUpdateView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, id=pk)
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Category name is required.')
            return HttpResponseRedirect(reverse_lazy('inventory:category_list'))
        category.name = name.upper()
        category.save(update_fields=['name'])
        messages.success(request, f'Category renamed to "{name}".')
        return HttpResponseRedirect(reverse_lazy('inventory:category_list'))


class CategoryDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, id=pk)
        name = category.name
        if category.products.exists():
            messages.error(request, f'Cannot delete "{name}" — it has {category.products.count()} product(s) assigned.')
            return HttpResponseRedirect(reverse_lazy('inventory:category_list'))
        category.delete()
        messages.success(request, f'Category "{name}" deleted.')
        return HttpResponseRedirect(reverse_lazy('inventory:category_list'))


class CategoryCreateQuickView(ManagerOrAdminMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Name is required.'}, status=400)
        category = Category.objects.create(name=name.upper())
        return JsonResponse({'id': category.id, 'name': category.name})


class BulkProductUploadView(ManagerOrAdminMixin, TemplateView):
    template_name = 'inventory/bulk_product_upload.html'

    def post(self, request):
        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a CSV file to upload.')
            return self.get(request)

        try:
            csv_text = csv_file.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            messages.error(request, 'File must be UTF-8 encoded.')
            return self.get(request)

        dry_run = request.POST.get('dry_run') == 'on'

        try:
            report = bulk_seed_products_csv(csv_text, dry_run=dry_run, received_by=request.user)
        except ValueError as e:
            messages.error(request, str(e))
            return self.get(request)

        if dry_run:
            messages.info(request, f"DRY RUN: Would create {report['vendors']} vendor(s), {report['products']} product(s), {report['recipes']} recipe link(s), {report['receipts']} receipt(s).")
        else:
            messages.success(request, f"Created {report['vendors']} vendor(s), {report['products']} product(s), {report['recipes']} recipe link(s), {report['receipts']} receipt(s).")

        if report['skipped']:
            for s in report['skipped']:
                messages.warning(request, s)
        if report['errors']:
            for e in report['errors']:
                messages.error(request, e)

        return self.get(request)


class BulkProductTemplateView(ManagerOrAdminMixin, View):

    def get(self, request):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['vendor_name', 'name', 'sku', 'category_name', 'cost_price', 'retail_price', 'discount_price', 'is_on_sale', 'is_service', 'is_variable_weight', 'stock_quantity', 'min_stock_level', 'child_sku', 'child_qty'])
        writer.writerow(['Acme Supply', 'Sourdough Bread', '', 'Bakery', '2.50', '5.99', '', '', '', '', '50', '10', 'FLO-001', '0.5'])
        writer.writerow(['Acme Supply', 'Whole Wheat', '', 'Bakery', '2.75', '6.49', '4.99', 'TRUE', '', '', '30', '5', 'FLO-001', '0.5'])
        writer.writerow(["Bob's Farm", 'Organic Flour', 'FLO-001', 'Ingredients', '1.00', '2.50', '', '', '', '', '200', '20', '', ''])
        content = buffer.getvalue()
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="product_template.csv"'
        return response


class RepackView(LoginRequiredMixin, TemplateView):
    template_name = 'inventory/repack.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['bulk_products'] = Product.objects.filter(
            stock_quantity__gt=0
        ).select_related('vendor').order_by('name')

        markup_setting = SystemSetting.objects.filter(key='DEFAULT_MARKUP_RATE').first()
        context['markup_rate'] = float(markup_setting.value) if markup_setting else 0.15

        parent_id = self.request.GET.get('parent')
        if parent_id:
            parent = get_object_or_404(Product, id=parent_id)
            context['selected_parent'] = parent
            context['child_breakdowns'] = RecipeIngredient.objects.filter(
                parent_product=parent
            ).select_related('child_product')

        return context

    def post(self, request):
        action = request.POST.get('action')

        if action == 'add_child':
            if not request.user.is_manager:
                messages.error(request, 'Only managers can add child products.')
                return HttpResponseRedirect(reverse_lazy('inventory:repack') + (f'?parent={request.POST.get("parent_id")}' if request.POST.get('parent_id') else ''))

            parent_id = request.POST.get('parent_id')
            name = request.POST.get('name', '').strip()
            retail_price = request.POST.get('retail_price', '').strip()
            cost_price = request.POST.get('cost_price', '').strip()
            qty_per_parent = request.POST.get('qty_per_parent', '').strip()

            if not all([parent_id, name, retail_price, qty_per_parent]):
                messages.error(request, 'Name, Retail Price, and Qty per Parent are required.')
                return HttpResponseRedirect(reverse_lazy('inventory:repack') + f'?parent={parent_id}')

            parent = get_object_or_404(Product, id=parent_id)

            dupes = RecipeIngredient.objects.filter(
                parent_product=parent,
                child_product__name__iexact=name,
            )
            if dupes.exists():
                messages.error(request, f'A child product named "{name}" already exists for "{parent.name}".')
                return HttpResponseRedirect(reverse_lazy('inventory:repack') + f'?parent={parent_id}')

            child = Product.objects.create(
                name=name,
                retail_price=Decimal(retail_price),
                cost_price=Decimal(cost_price) if cost_price else Decimal('0'),
                stock_quantity=Decimal('0'),
                vendor=parent.vendor,
                category=parent.category,
            )
            child.sku = generate_sku(child.category.name if child.category else 'GEN', child.id)
            child.save(update_fields=['sku'])

            RecipeIngredient.objects.create(
                parent_product=parent,
                child_product=child,
                quantity_required=Decimal(qty_per_parent),
            )

            messages.success(request, f'Child product "{name}" created.')
            return HttpResponseRedirect(reverse_lazy('inventory:repack') + f'?parent={parent_id}')

        elif action == 'execute':
            parent_id = request.POST.get('parent_id')
            parent_qty = request.POST.get('parent_qty', '').strip()

            if not parent_id or not parent_qty:
                messages.error(request, 'Select a parent product and enter quantity.')
                return HttpResponseRedirect(reverse_lazy('inventory:repack'))

            try:
                result = execute_repack(int(parent_id), Decimal(parent_qty))
                parts = ', '.join(f'{c["qty"]}x {c["name"]}' for c in result['children'])
                messages.success(
                    request,
                    f'Repacked {result["parent_consumed"]}x "{result["parent"]}". '
                    f'Created: {parts}. Remaining: {result["parent_remaining"]}.',
                )
            except ValueError as e:
                messages.error(request, str(e))

            return HttpResponseRedirect(reverse_lazy('inventory:repack') + f'?parent={parent_id}')

        return HttpResponseRedirect(reverse_lazy('inventory:repack'))


class RepackProductSearchView(LoginRequiredMixin, View):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        products = Product.objects.filter(
            stock_quantity__gt=0
        ).filter(
            Q(sku__icontains=q) | Q(name__icontains=q)
        ).select_related('vendor').order_by('name')[:15] if q else []
        html = render_to_string('inventory/partials/repack_product_search.html', {'products': products, 'q': q}, request=request)
        return HttpResponse(html)


class BundleListView(ManagerOrAdminMixin, ListView):
    model = Bundle
    template_name = 'inventory/bundle_list.html'
    context_object_name = 'bundles'
    ordering = ['-created_at']

    def get_queryset(self):
        return Bundle.objects.prefetch_related('items__product').all()


class BundleCreateView(ManagerOrAdminMixin, View):
    def get(self, request):
        return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Bundle name is required.')
            return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

        row_ids = {int(k.removeprefix('product_')) for k in request.POST if k.startswith('product_')}
        if not row_ids:
            messages.error(request, 'Add at least one product to the bundle.')
            return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

        bundle = Bundle.objects.create(name=name)
        for rid in sorted(row_ids):
            product_id = request.POST.get(f'product_{rid}')
            qty = request.POST.get(f'qty_{rid}', '1')
            try:
                qty = Decimal(qty)
            except Exception:
                qty = Decimal('1')
            BundleItem.objects.create(bundle=bundle, product_id=int(product_id), quantity=qty)

        messages.success(request, f'Bundle "{name}" created.')
        return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))


class BundleProductSearchView(ManagerOrAdminMixin, View):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        products = Product.objects.filter(
            Q(sku__icontains=q) | Q(name__icontains=q)
        ).order_by('name')[:15] if q else []
        html = render_to_string('inventory/partials/bundle_product_search.html',
                                {'products': products, 'q': q}, request=request)
        return HttpResponse(html)


class BundleUpdateView(ManagerOrAdminMixin, View):
    def get(self, request, pk):
        return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

    def post(self, request, pk):
        bundle = get_object_or_404(Bundle, pk=pk)
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Bundle name is required.')
            return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

        description = request.POST.get('description', '')
        is_active = request.POST.get('is_active') == 'true'

        row_ids = {int(k.removeprefix('product_')) for k in request.POST if k.startswith('product_')}
        if not row_ids:
            messages.error(request, 'Add at least one product to the bundle.')
            return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))

        bundle.name = name
        bundle.description = description
        bundle.is_active = is_active
        bundle.save()

        bundle.items.all().delete()
        for rid in sorted(row_ids):
            product_id = request.POST.get(f'product_{rid}')
            qty = request.POST.get(f'qty_{rid}', '1')
            try:
                qty = Decimal(qty)
            except Exception:
                qty = Decimal('1')
            BundleItem.objects.create(bundle=bundle, product_id=int(product_id), quantity=qty)

        messages.success(request, f'Bundle "{name}" updated.')
        return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))


class BundleDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        bundle = get_object_or_404(Bundle, pk=pk)
        name = bundle.name
        bundle.delete()
        messages.success(request, f'Bundle "{name}" deleted.')
        return HttpResponseRedirect(reverse_lazy('inventory:bundle_list'))
