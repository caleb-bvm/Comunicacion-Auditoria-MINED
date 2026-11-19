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


def _user_sessions(user):
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                yield session
        except Exception:
            continue


def close_user_sessions(user, keep_session_key=None):
    """Invalidate every authenticated session belonging to a user, except the one kept."""
    closed = 0
    for session in list(_user_sessions(user)):
        if keep_session_key and session.session_key == keep_session_key:
            continue
        session.delete()
        closed += 1
    return closed


def count_user_sessions(user):
    return sum(1 for _ in _user_sessions(user))


def describe_device(user_agent):
    """Nombre corto y legible del dispositivo; nunca se guarda el agente completo."""
    agent = (user_agent or "").lower()
    if "edg/" in agent:
        browser = "Edge"
    elif "opr/" in agent or "opera" in agent:
        browser = "Opera"
    elif "firefox/" in agent or "fxios/" in agent:
        browser = "Firefox"
    elif "chrome/" in agent or "crios/" in agent:
        browser = "Chrome"
    elif "safari/" in agent:
        browser = "Safari"
    else:
        browser = "Navegador"
    if "android" in agent:
        system = "teléfono Android"
    elif "iphone" in agent:
        system = "iPhone"
    elif "ipad" in agent:
        system = "iPad"
    elif "windows" in agent:
        system = "Windows"
    elif "mac os" in agent or "macintosh" in agent:
        system = "Mac"
    elif "linux" in agent:
        system = "Linux"
    else:
        return browser
    return f"{browser} en {system}"
