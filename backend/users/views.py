from typing import Any

from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import ProtectedError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from accounting.models import Ledger
from inventory.models import InventoryReceipt, PurchaseOrder
from sales.models import Session, Transaction

from .forms import UserCreateForm, UserUpdateForm
from .models import User


class CustomLoginView(LoginView):
    template_name = "users/login.html"
    next_page = reverse_lazy("sales:dashboard")


class CustomLogoutView(LogoutView):
    http_method_names = ["get", "post", "options"]
    next_page = reverse_lazy("users:login")


class ManagerOrAdminMixin(UserPassesTestMixin):
    request: Any

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_manager or user.is_admin)


class UserListView(ManagerOrAdminMixin, ListView):
    model = User
    template_name = "users/user_list.html"
    context_object_name = "users"
    queryset = User.objects.exclude(username='admin')


class UserCreateView(ManagerOrAdminMixin, CreateView):
    model = User
    form_class = UserCreateForm
    template_name = "users/user_list.html"
    success_url = reverse_lazy("users:user_list")

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(self.success_url)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if not self.request.user.is_admin and form.cleaned_data.get('role') == User.Role.ADMIN:
            messages.error(self.request, "Only admins can create admin users.")
            return HttpResponseRedirect(self.success_url)
        messages.success(self.request, "User created successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for err in errors:
                messages.error(self.request, err)
        return HttpResponseRedirect(self.success_url)


class UserUpdateView(ManagerOrAdminMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = "users/user_list.html"
    success_url = reverse_lazy("users:user_list")

    def get(self, request, *args, **kwargs):
        return HttpResponseRedirect(self.success_url)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if not self.request.user.is_admin and form.cleaned_data.get('role') == User.Role.ADMIN:
            messages.error(self.request, "Only admins can assign the admin role.")
            return HttpResponseRedirect(self.success_url)
        messages.success(self.request, "User updated successfully.")
        return super().form_valid(form)

    def form_invalid(self, form):
        for field, errors in form.errors.items():
            for err in errors:
                messages.error(self.request, err)
        return HttpResponseRedirect(self.success_url)


class UserToggleActiveView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, id=pk)
        if user == request.user:
            messages.error(request, "You cannot deactivate your own account.")
            return HttpResponseRedirect(reverse_lazy("users:user_list"))
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        status = "activated" if user.is_active else "deactivated"
        messages.success(request, f'User "{user.username}" {status}.')
        return HttpResponseRedirect(reverse_lazy("users:user_list"))


class UserDeleteView(ManagerOrAdminMixin, View):
    def post(self, request, pk):
        user_to_delete = get_object_or_404(User, id=pk)

        if user_to_delete == request.user:
            messages.error(request, "You cannot delete your own account.")
            return HttpResponseRedirect(reverse_lazy("users:user_list"))

        if (
            user_to_delete.is_admin
            and User.objects.filter(role=User.Role.ADMIN).count() <= 1
        ):
            messages.error(request, "Cannot delete the last admin account.")
            return HttpResponseRedirect(reverse_lazy("users:user_list"))

        bypass_pin = request.POST.get("bypass_pin", "")
        username = user_to_delete.username
        try:
            user_to_delete.delete()
        except ProtectedError:
            if request.user.is_admin and bypass_pin and check_password(bypass_pin, request.user.pin_code):
                self._force_delete_user(user_to_delete, request.user)
                messages.success(request, f'User "{username}" deleted (admin bypass).')
            else:
                messages.error(
                    request,
                    f'Cannot delete "{username}" — they have related records (transactions, sessions, etc.). Deactivate them instead.',
                )
            return HttpResponseRedirect(reverse_lazy("users:user_list"))
        messages.success(request, f'User "{username}" deleted.')
        return HttpResponseRedirect(reverse_lazy("users:user_list"))

    def _force_delete_user(self, user_to_delete, admin_user):
        PurchaseOrder.objects.filter(created_by=user_to_delete).update(created_by=None)
        InventoryReceipt.objects.filter(received_by=user_to_delete).update(received_by=None)
        Session.objects.filter(opened_by=user_to_delete).update(opened_by=None)
        Session.objects.filter(closed_by=user_to_delete).update(closed_by=None)
        Transaction.objects.filter(cashier=user_to_delete).update(cashier=admin_user)
        Ledger.objects.filter(logged_by=user_to_delete).update(logged_by=admin_user)
        user_to_delete.delete()
