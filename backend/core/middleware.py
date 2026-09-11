from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from .models import BusinessInfo, SystemSetting

DEFAULT_TIMEOUT = 300
MIN_TIMEOUT = 60
MAX_TIMEOUT = 1800


def get_idle_timeout():
    enabled_row = SystemSetting.objects.filter(key='SESSION_IDLE_TIMEOUT_ENABLED').first()
    if enabled_row and enabled_row.value == 'false':
        return 0

    timeout_row = SystemSetting.objects.filter(key='SESSION_IDLE_TIMEOUT').first()
    try:
        timeout = int(timeout_row.value) if timeout_row else DEFAULT_TIMEOUT
    except (ValueError, TypeError):
        timeout = DEFAULT_TIMEOUT

    return max(MIN_TIMEOUT, min(MAX_TIMEOUT, timeout))


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            timeout = get_idle_timeout()
            if timeout > 0:
                last = request.session.get('last_activity')
                now = timezone.now().timestamp()

                if last is not None and (now - last) > timeout:
                    logout(request)
                    return HttpResponseRedirect(reverse('users:login'))

                request.session['last_activity'] = now

        return self.get_response(request)


class SetupCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path_info
            if (
                path.startswith('/setup/')
                or path.startswith('/settings/')
                or path.startswith('/login/')
                or path.startswith('/admin/')
                or path.startswith('/static/')
                or path.startswith('/media/')
            ):
                return self.get_response(request)

            if not BusinessInfo.objects.exists():
                return HttpResponseRedirect(reverse('setup'))

        return self.get_response(request)
