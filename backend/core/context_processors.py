from .models import BusinessInfo


def business_info(request):
    info = BusinessInfo.objects.first()
    return {'business': info}
