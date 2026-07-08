from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import check_password

from .models import User


class PinOrPasswordBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if password is None or username is None:
            return None
        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            return None
        if user.pin_code and check_password(password, user.pin_code):
            return user
        if check_password(password, user.password):
            return user
        return None
