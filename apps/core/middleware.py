import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect


class SecurityHeadersMiddleware:
    """Cabeceras defensivas que también se aplican en el entorno de desarrollo."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        expired = False
        was_authenticated = request.user.is_authenticated
        if request.user.is_authenticated:
            now = int(time.time())
            started = request.session.setdefault("authenticated_at", now)
            if now - started >= settings.SESSION_ABSOLUTE_TIMEOUT:
                logout(request)
                expired = True
        response = redirect("login") if expired else self.get_response(request)
        if was_authenticated or request.user.is_authenticated:
            response.headers["Cache-Control"] = "private, no-store"
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "font-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response
