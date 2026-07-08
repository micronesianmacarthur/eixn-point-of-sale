from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.edit import CreateView, UpdateView, FormView
from django.urls import reverse_lazy
from django import forms
from django.contrib import messages

from .models import BusinessInfo, SystemSetting


class SettingsForm(forms.Form):
    default_markup_rate = forms.DecimalField(
        max_digits=5, decimal_places=4, required=True,
        label='Default Markup Rate',
        help_text='Markup rate for suggested retail price (e.g. 0.15 = 15%)',
    )


class SettingsView(LoginRequiredMixin, FormView):
    template_name = 'core/settings.html'
    form_class = SettingsForm
    success_url = reverse_lazy('settings')

    def get_initial(self):
        setting = SystemSetting.objects.filter(key='DEFAULT_MARKUP_RATE').first()
        return {'default_markup_rate': setting.value if setting else '0.15'}

    def form_valid(self, form):
        rate = form.cleaned_data['default_markup_rate']
        SystemSetting.objects.update_or_create(
            key='DEFAULT_MARKUP_RATE',
            defaults={'value': str(rate), 'description': 'Default markup rate for suggested retail price calculations'},
        )
        messages.success(self.request, 'Settings saved.')
        return super().form_valid(form)


class BusinessInfoForm(forms.ModelForm):
    class Meta:
        model = BusinessInfo
        fields = ['business_name', 'contact_phone', 'contact_email', 'website', 'logo']
        widgets = {
            'business_name': forms.TextInput(attrs={'class': 'w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500'}),
            'contact_phone': forms.TextInput(attrs={'class': 'w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500'}),
            'contact_email': forms.EmailInput(attrs={'class': 'w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500'}),
            'website': forms.URLInput(attrs={'class': 'w-full bg-white rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500'}),
            'logo': forms.FileInput(attrs={'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100'}),
        }

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if logo and logo.size > 3 * 1024 * 1024:
            raise forms.ValidationError('Logo image must be under 3 MB.')
        return logo


class SetupWizardView(LoginRequiredMixin, CreateView):
    model = BusinessInfo
    form_class = BusinessInfoForm
    template_name = 'core/setup.html'
    success_url = reverse_lazy('sales:dashboard')

    def form_valid(self, form):
        messages.success(self.request, 'Business information saved. Welcome aboard!')
        return super().form_valid(form)


class BusinessInfoUpdateView(LoginRequiredMixin, UpdateView):
    model = BusinessInfo
    form_class = BusinessInfoForm
    template_name = 'core/setup.html'
    success_url = reverse_lazy('settings')

    def get_object(self, queryset=None):
        return BusinessInfo.objects.first()

    def form_valid(self, form):
        messages.success(self.request, 'Business information updated.')
        return super().form_valid(form)

