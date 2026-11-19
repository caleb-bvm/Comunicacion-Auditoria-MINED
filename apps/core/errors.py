"""Páginas de error con los datos que necesita soporte técnico para diagnosticar.

Cada página explica a la persona qué pasó y qué puede hacer, y muestra un recuadro con
el código, la dirección, la hora y, en los errores del sistema, una referencia que
también queda en el registro del servidor. Nunca muestran trazas ni datos internos.

Los errores 400 y 500 y el fallo CSRF se renderizan sin RequestContext: pueden ocurrir
con la sesión o la base de datos dañadas, así que no deben depender de ellas.
"""

import logging
import re
import secrets

from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseServerError,
)
from django.middleware import csrf
from django.shortcuts import render
from django.template import loader
from django.utils import timezone

logger = logging.getLogger("apps.core.errors")

# Los enlaces de activación y de restablecimiento llevan un secreto en la ruta.
SECRET_PATH = re.compile(r"^/(activar-cuenta|restablecer)/.+$")
MAX_PATH_LENGTH = 200

CSRF_REASONS = {
    csrf.REASON_NO_CSRF_COOKIE: "El navegador no envió la cookie de seguridad (cookies bloqueadas o sesión vencida).",
    csrf.REASON_CSRF_TOKEN_MISSING: "El formulario llegó sin su código de seguridad.",
    csrf.REASON_NO_REFERER: "El navegador no indicó desde qué página se envió el formulario.",
    csrf.REASON_MALFORMED_REFERER: "La página de origen que informó el navegador no es válida.",
    csrf.REASON_INSECURE_REFERER: "El formulario se envió desde una página sin HTTPS.",
}


def safe_path(request):
    """Ruta solicitada, sin parámetros y sin los secretos de los enlaces de un solo uso."""
    path = SECRET_PATH.sub(r"/\1/[oculto]/", request.path)
    if len(path) > MAX_PATH_LENGTH:
        path = f"{path[:MAX_PATH_LENGTH]}…"
    return path


def error_details(request, status, label, reference=""):
    return {
        "status": status,
        "label": label,
        "path": safe_path(request),
        "method": request.method,
        "occurred_at": timezone.localtime(),
        "reference": reference,
    }


def new_reference():
    return secrets.token_hex(4).upper()


def user_reference(request):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"usuario {user.pk}"
    return "sin sesión"


def bad_request(request, exception, template_name="400.html"):
    context = {"error": error_details(request, 400, "Bad Request")}
    return HttpResponseBadRequest(loader.get_template(template_name).render(context))


def permission_denied(request, exception, template_name="403.html"):
    context = {
        "error": error_details(request, 403, "Forbidden"),
        "exception": str(exception) if exception else "",
    }
    return HttpResponseForbidden(render(request, template_name, context).content)


def page_not_found(request, exception, template_name="404.html"):
    context = {"error": error_details(request, 404, "Not Found")}
    return HttpResponseNotFound(render(request, template_name, context).content)


def server_error(request, template_name="500.html"):
    reference = new_reference()
    # Django ya registra la traza; esta línea une la referencia que ve la persona con ella.
    logger.error(
        "Referencia %s: error 500 en %s %s (%s)",
        reference, request.method, safe_path(request), user_reference(request),
        exc_info=True,
    )
    context = {"error": error_details(request, 500, "Internal Server Error", reference)}
    return HttpResponseServerError(loader.get_template(template_name).render(context))


def csrf_failure(request, reason="", template_name="403_csrf.html"):
    reference = new_reference()
    logger.warning(
        "Referencia %s: formulario rechazado por CSRF en %s %s (%s): %s",
        reference, request.method, safe_path(request), user_reference(request), reason,
    )
    explanation = CSRF_REASONS.get(reason, "")
    if not explanation and reason.startswith("Origin checking failed"):
        explanation = "La dirección desde la que se envió no coincide con la del sistema."
    elif not explanation and reason.startswith("Referer checking failed"):
        explanation = "La página de origen no coincide con la dirección del sistema."
    context = {
        "error": error_details(request, 403, "Forbidden (CSRF)", reference),
        "reason": explanation or "El código de seguridad del formulario no coincide con el de la sesión.",
    }
    return HttpResponseForbidden(loader.get_template(template_name).render(context))


def method_not_allowed(request, response):
    """Página para un 405: Django lo devuelve sin contenido (require_POST y similares)."""
    context = {
        "error": error_details(request, 405, "Method Not Allowed"),
        "allowed": response.get("Allow", ""),
    }
    content = render(request, "405.html", context).content
    response.content = content
    response["Content-Type"] = "text/html; charset=utf-8"
    return response
