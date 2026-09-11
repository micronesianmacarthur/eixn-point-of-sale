from .models import BusinessInfo, SystemSetting


def business_info(request):
    info = BusinessInfo.objects.first()
    return {'business': info}


def session_timeout_config(request):
    enabled_row = SystemSetting.objects.filter(key='SESSION_IDLE_TIMEOUT_ENABLED').first()
    timeout_enabled = not (enabled_row and enabled_row.value == 'false')

    timeout_row = SystemSetting.objects.filter(key='SESSION_IDLE_TIMEOUT').first()
    try:
        timeout_seconds = int(timeout_row.value) if timeout_row else 300
    except (ValueError, TypeError):
        timeout_seconds = 300

    return {
        'session_timeout_enabled': timeout_enabled,
        'session_timeout_seconds': timeout_seconds,
    }
