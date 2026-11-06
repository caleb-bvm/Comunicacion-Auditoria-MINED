"""Etiquetas de plantilla del sistema de diseño «Claro y directo»."""

from datetime import date, timedelta

from django import template
from django.utils import timezone
from django.utils.dateformat import format as format_date

register = template.Library()

# Estado de una recomendación → (tono del chip, ícono, texto corto).
RECOMMENDATION_STATUS = {
    "pending": ("neutral", "pending", "Pendiente"),
    "submitted": ("info", "send", "Enviada"),
    "under_review": ("review", "search", "En revisión"),
    "correction_required": ("correction", "edit", "Corregir"),
    "complied": ("success", "check", "Cumplida"),
    "partial": ("success", "half", "Parcialmente cumplida"),
    "not_complied": ("danger", "close", "No cumplida"),
}

# Estado de un expediente → (tono del chip, ícono, texto corto).
CASE_STATUS = {
    "draft": ("neutral", "edit", "Borrador"),
    "pending_publication": ("info", "send", "Por publicar"),
    "published": ("info", "send", "Enviado"),
    "in_response": ("neutral", "pending", "Sin respuesta"),
    "under_review": ("review", "search", "En revisión"),
    "correction_required": ("correction", "edit", "Corregir"),
    "pending_closure": ("success", "check", "Cierre pedido"),
    "closed": ("success", "check", "Cerrado"),
}

DUE_SOON_DAYS = 7


def short_date(value, today):
    pattern = "j b" if value.year == today.year else "j b Y"
    return format_date(value, pattern)


def deadline_state(deadline, today=None):
    """Describe un plazo en palabras: «Venció el 4 oct», «Vence hoy», «Vence el 11 nov»."""
    if not isinstance(deadline, date):
        return None
    today = today or timezone.localdate()
    if deadline < today:
        return {"tone": "danger", "icon": "alert", "label": f"Venció el {short_date(deadline, today)}"}
    if deadline == today:
        return {"tone": "danger", "icon": "alert", "label": "Vence hoy"}
    tone = "warning" if deadline <= today + timedelta(days=DUE_SOON_DAYS) else "neutral"
    return {"tone": tone, "icon": "clock", "label": f"Vence el {short_date(deadline, today)}"}


@register.inclusion_tag("includes/ui/icon.html")
def ui_icon(name):
    return {"name": name}


@register.inclusion_tag("includes/ui/chip.html")
def ui_status_chip(status, label=None):
    tone, icon, short_label = RECOMMENDATION_STATUS.get(status, ("neutral", "pending", status))
    return {"tone": tone, "icon": icon, "label": label or short_label}


@register.inclusion_tag("includes/ui/chip.html")
def ui_case_status_chip(status):
    tone, icon, label = CASE_STATUS.get(status, ("neutral", "pending", status))
    return {"tone": tone, "icon": icon, "label": label}


@register.inclusion_tag("includes/ui/chip.html")
def ui_deadline_chip(deadline):
    state = deadline_state(deadline)
    if state is None:
        return {"tone": "neutral", "icon": "clock", "label": "Sin fecha límite"}
    return state


@register.simple_tag
def ui_deadline_label(deadline):
    state = deadline_state(deadline)
    return state["label"] if state else "Sin fecha límite"


@register.filter
def ui_lines(value):
    """Divide un texto en líneas no vacías, sin viñetas ni guiones iniciales."""
    if not value:
        return []
    lines = []
    for line in str(value).splitlines():
        cleaned = line.strip().lstrip("-•*·").strip()
        if cleaned:
            lines.append(cleaned)
    return lines
