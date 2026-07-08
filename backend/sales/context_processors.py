from .models import Session


def active_session(request):
    return {
        'active_session': Session.objects.filter(status=Session.Status.OPEN).first()
    }
