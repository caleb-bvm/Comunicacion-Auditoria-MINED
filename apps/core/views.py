from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

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
