from django.http import HttpResponse


def client_ip(request):
    # No confiar en X-Forwarded-For enviado por el visitante.
    return request.META.get("REMOTE_ADDR")


def lockout_response(request, credentials=None, *args, **kwargs):
    response = HttpResponse(
        "Demasiados intentos de acceso. Espere 15 minutos antes de volver a intentar.",
        status=429, content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = "900"
    response["Cache-Control"] = "no-store"
    return response
