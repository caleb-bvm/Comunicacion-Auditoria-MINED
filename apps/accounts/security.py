from django.http import HttpResponse
from django.contrib.sessions.models import Session
from django.utils import timezone


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


def close_user_sessions(user):
    """Invalidate every authenticated session belonging to a user."""
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                session.delete()
        except Exception:
            continue
