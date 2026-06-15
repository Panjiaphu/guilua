from django.http import HttpResponse


def healthz(request):
    return HttpResponse("ok\n", content_type="text/plain")
