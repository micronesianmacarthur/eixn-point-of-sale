from functools import wraps

from django.shortcuts import redirect

from .models import Session


def require_open_session(view_func):
    @wraps(view_func)
    def _wrapper(request, *args, **kwargs):
        open_session = Session.objects.filter(status=Session.Status.OPEN).first()
        if open_session is None:
            return redirect('sales:session_create')
        return view_func(request, *args, **kwargs)
    return _wrapper
