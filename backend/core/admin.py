from django.contrib import admin

from .models import BusinessInfo, SystemSetting


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'description')
    search_fields = ('key',)


@admin.register(BusinessInfo)
class BusinessInfoAdmin(admin.ModelAdmin):
    list_display = ('business_name', 'contact_phone', 'contact_email', 'website')
    search_fields = ('business_name',)
