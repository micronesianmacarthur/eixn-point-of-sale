from django import forms
from .models import Vendor


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            'name',
            'contact_person',
            'phone',
            'email',
            'address_1',
            'city',
            'state',
            'zip_code',
            'country',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'contact_person': forms.TextInput(attrs={'class': 'input'}),
            'phone': forms.TextInput(attrs={'class': 'input'}),
            'email': forms.EmailInput(attrs={'class': 'input'}),
            'address_1': forms.TextInput(attrs={'class': 'input'}),
            'city': forms.TextInput(attrs={'class': 'input'}),
            'state': forms.TextInput(attrs={'class': 'input'}),
            'zip_code': forms.TextInput(attrs={'class': 'input'}),
            'country': forms.TextInput(attrs={'class': 'input'}),
        }