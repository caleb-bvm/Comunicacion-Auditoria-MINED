import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .templatetags.ui import SEVERITY_LEVELS, STATUS_STYLES


def ui_reference(request):
    """Muestra los componentes del sistema de diseño. Solo existe en desarrollo."""
    if not settings.DEBUG:
        raise Http404
    today = timezone.localdate()
    return render(
        request,
        "dev/ui.html",
        {
            "status_families": [(family, list(values)) for family, values in STATUS_STYLES.items()],
            "severity_examples": [("risk", value) for value in SEVERITY_LEVELS["risk"]] + [("attention", value) for value in SEVERITY_LEVELS["attention"]],
            "deadlines": [today - timedelta(days=33), today, today + timedelta(days=3), today + timedelta(days=40)],
        },
    )


# Lo que el service worker guarda para mostrar la página sin conexión. Debe coincidir con
# lo que carga templates/offline.html.
OFFLINE_ASSETS = (
    "css/app.css",
    "css/tokens.css",
    "css/bridge.css",
    "css/components.css",
    "js/offline.js",
    "img/favicon.svg",
)


@require_GET
def offline_page(request):
    """Página que el service worker muestra cuando el dispositivo no llega al servidor.

    No usa datos de la sesión: se guarda en el navegador y debe servir para cualquier cuenta.
    """
    return HttpResponse(render_to_string("offline.html"))


@require_GET
def service_worker(request):
    """Service worker en la raíz para que su alcance cubra todo el sistema."""
    offline_url = reverse("offline")
    assets = [offline_url, *(static(path) for path in OFFLINE_ASSETS)]
    # La versión cambia con la página o con los estáticos (nombres con hash en producción),
    # así el navegador renueva la copia guardada en cada actualización.
    fingerprint = hashlib.sha256(render_to_string("offline.html").encode())
    fingerprint.update(" ".join(assets).encode())
    script = render_to_string(
        "sw.js",
        {
            "cache_name": json.dumps(f"siga-sin-conexion-{fingerprint.hexdigest()[:12]}"),
            "offline_url": json.dumps(offline_url),
            "assets": json.dumps(assets),
        },
    )
    response = HttpResponse(script, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    return response
