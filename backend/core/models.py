from django.db import models
from django.utils.translation import gettext_lazy as _


class SystemSetting(models.Model):
    key = models.CharField(max_length=100, unique=True, verbose_name=_('Key'))
    value = models.CharField(max_length=255, verbose_name=_('Value'))
    description = models.TextField(blank=True, verbose_name=_('Description'))

    class Meta:
        verbose_name = _('System Setting')
        verbose_name_plural = _('System Settings')

    def __str__(self):
        return self.key


class BusinessInfo(models.Model):
    business_name = models.CharField(max_length=255, verbose_name=_('Business Name'))
    contact_phone = models.CharField(max_length=50, blank=True, verbose_name=_('Contact Phone'))
    contact_email = models.EmailField(blank=True, verbose_name=_('Contact Email'))
    website = models.URLField(blank=True, verbose_name=_('Website'))
    logo = models.ImageField(upload_to='logos/', blank=True, verbose_name=_('Logo'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))

    class Meta:
        verbose_name = _('Business Information')
        verbose_name_plural = _('Business Information')

    def __str__(self):
        return self.business_name
