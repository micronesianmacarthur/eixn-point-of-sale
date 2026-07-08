from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic.base import RedirectView

from . import views

app_name = 'core'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/sales/dashboard/', permanent=False), name='home'),
    path('setup/', views.SetupWizardView.as_view(), name='setup'),
    path('settings/', views.SettingsView.as_view(), name='settings'),
    path('settings/business/', views.BusinessInfoUpdateView.as_view(), name='business_settings'),
    path('', include('users.urls')),
    path('customers/', include('customers.urls')),
    path('inventory/', include('inventory.urls')),
    path('sales/', include('sales.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
