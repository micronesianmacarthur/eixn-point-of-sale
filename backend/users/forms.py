from django import forms
from django.contrib.auth.hashers import check_password
from django.contrib.auth.forms import UserCreationForm

from .models import User


class UserCreateForm(UserCreationForm):
    pin_code = forms.CharField(max_length=4, required=False, help_text='4-digit PIN for cashier auth')

    class Meta:
        model = User
        fields = ('username', 'email', 'role', 'pin_code', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.request_user and not self.request_user.is_admin:
            self.fields['role'].choices = [
                c for c in User.Role.choices if c[0] != User.Role.ADMIN
            ]

    def clean_role(self):
        role = self.cleaned_data.get('role')
        if role == User.Role.ADMIN and self.request_user and not self.request_user.is_admin:
            raise forms.ValidationError('Only admins can create admin users.')
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        raw_pin = self.cleaned_data.get('pin_code')
        if raw_pin:
            user.set_pin_code(raw_pin)
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    current_pin = forms.CharField(max_length=4, required=False, label='Current PIN')
    new_pin = forms.CharField(max_length=4, required=False, label='New PIN')
    confirm_pin = forms.CharField(max_length=4, required=False, label='Confirm PIN')
    current_password = forms.CharField(required=False, label='Current Password', widget=forms.PasswordInput)
    new_password = forms.CharField(required=False, label='New Password', widget=forms.PasswordInput)
    confirm_password = forms.CharField(required=False, label='Confirm Password', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('username', 'email', 'role',)

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.request_user and not self.request_user.is_admin:
            self.fields['role'].choices = [
                c for c in User.Role.choices if c[0] != User.Role.ADMIN
            ]

    def clean_role(self):
        role = self.cleaned_data.get('role')
        if role == User.Role.ADMIN and self.request_user and not self.request_user.is_admin:
            raise forms.ValidationError('Only admins can assign the admin role.')
        return role

    def clean_current_pin(self):
        current_pin = self.cleaned_data.get('current_pin', '')
        new_pin = self.cleaned_data.get('new_pin', '')
        is_self = self.request_user == self.instance
        if new_pin and is_self and not current_pin:
            raise forms.ValidationError('Current PIN is required to set a new PIN.')
        if current_pin and is_self and self.instance.pin_code and not check_password(current_pin, self.instance.pin_code):
            raise forms.ValidationError('Current PIN is incorrect.')
        return current_pin

    def clean_confirm_pin(self):
        new_pin = self.cleaned_data.get('new_pin', '')
        confirm_pin = self.cleaned_data.get('confirm_pin', '')
        if new_pin and new_pin != confirm_pin:
            raise forms.ValidationError('New PIN and confirm PIN do not match.')
        return confirm_pin

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password', '')
        new_password = self.cleaned_data.get('new_password', '')
        is_self = self.request_user == self.instance
        if new_password and is_self and not current_password:
            raise forms.ValidationError('Current password is required to set a new password.')
        if current_password and is_self and not check_password(current_password, self.instance.password):
            raise forms.ValidationError('Current password is incorrect.')
        return current_password

    def clean_confirm_password(self):
        new_password = self.cleaned_data.get('new_password', '')
        confirm_password = self.cleaned_data.get('confirm_password', '')
        if new_password and new_password != confirm_password:
            raise forms.ValidationError('New password and confirm password do not match.')
        return confirm_password

    def save(self, commit=True):
        user = super().save(commit=False)
        new_pin = self.cleaned_data.get('new_pin', '')
        if new_pin:
            user.set_pin_code(new_pin)
        elif user.pk:
            existing = User.objects.get(pk=user.pk)
            user.pin_code = existing.pin_code
        new_password = self.cleaned_data.get('new_password', '')
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user
