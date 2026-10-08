from django import forms
from .models import Customer


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            'name',
            'phone',
            'email',
            'address_1',
            'city',
            'state',
            'zip_code',
            'country',
            'allow_pay_later',
            'credit_limit',
            'is_owner',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'address_1': forms.TextInput(attrs={'class': 'input'}),
            'city': forms.TextInput(attrs={'class': 'input'}),
            'state': forms.TextInput(attrs={'class': 'input'}),
            'zip_code': forms.TextInput(attrs={'class': 'input'}),
            'country': forms.TextInput(attrs={'class': 'input'}),
            'allow_pay_later': forms.CheckboxInput(attrs={'class': 'checkbox'}),
            'credit_limit': forms.NumberInput(attrs={'class': 'input', 'step': '0.01', 'min': '0'}),
            'is_owner': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }