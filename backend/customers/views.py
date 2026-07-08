from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from .models import Customer
from .services import process_customer_payment


class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 25


class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/customer_detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from sales.models import Transaction
        context['transactions'] = Transaction.objects.filter(
            customer=self.object
        ).exclude(status=Transaction.Status.VOIDED).order_by('-transaction_date')[:50]
        return context


class ManagerOrAdminMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_manager or user.is_admin)


class CustomerCreateView(ManagerOrAdminMixin, CreateView):
    model = Customer
    fields = ['name', 'phone', 'email', 'credit_limit', 'allow_pay_later', 'is_owner', 'loyalty_enabled']
    template_name = 'customers/customer_list.html'
    success_url = reverse_lazy('customers:customer_list')

    def form_valid(self, form):
        messages.success(self.request, f'Customer "{form.instance.name}" created.')
        return super().form_valid(form)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class CustomerUpdateView(ManagerOrAdminMixin, UpdateView):
    model = Customer
    fields = ['name', 'phone', 'email', 'credit_limit', 'allow_pay_later', 'is_owner', 'loyalty_enabled']
    template_name = 'customers/customer_list.html'
    success_url = reverse_lazy('customers:customer_list')

    def form_valid(self, form):
        messages.success(self.request, f'Customer "{form.instance.name}" updated.')
        return super().form_valid(form)

    def form_invalid(self, form):
        for error in form.errors.values():
            messages.error(self.request, error.as_text())
        return HttpResponseRedirect(self.success_url)


class CustomerPaymentView(LoginRequiredMixin, View):
    def post(self, request, pk):
        customer = get_object_or_404(Customer, id=pk)
        raw = request.POST.get('amount')
        if not raw:
            messages.error(request, 'Amount is required.')
        else:
            try:
                amount = Decimal(str(raw))
                process_customer_payment(customer_id=customer.id, amount=amount)
                messages.success(request, f'Payment of ${amount} applied to {customer.name}.')
            except (ValueError, DecimalException) as e:
                messages.error(request, str(e))
        return HttpResponseRedirect(reverse_lazy('customers:customer_detail', kwargs={'pk': pk}))
