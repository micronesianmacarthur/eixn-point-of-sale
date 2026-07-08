from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from .models import BusinessInfo


class IdleTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            last = request.session.get('last_activity')
            now = timezone.now().timestamp()
            timeout = settings.SESSION_IDLE_TIMEOUT

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
