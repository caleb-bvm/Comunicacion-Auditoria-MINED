from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone


def ui_reference(request):
    """Muestra los componentes del sistema de diseño. Solo existe en desarrollo."""
    if not settings.DEBUG:
        raise Http404
    today = timezone.localdate()
    return render(
        request,
        "dev/ui.html",
        {
            "statuses": [
                "pending",
                "submitted",
                "under_review",
                "correction_required",
                "complied",
                "partial",
                "not_complied",
            ],
            "deadlines": [today - timedelta(days=33), today, today + timedelta(days=3), today + timedelta(days=40)],
        },
    )
