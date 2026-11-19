"""Etiquetas de plantilla del sistema de diseño «Claro y directo»."""

from datetime import date, timedelta

from django import template
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.timesince import timesince

register = template.Library()

# Sistema de estados de SIGA-MINEDUCYT: cuatro colores y un neutro, cada uno con un solo significado.
#   danger  → problema: falló o venció. Actuar ahora. (relleno fuerte)
#   warning → requiere atención: todavía no falla, pero no está bien.
#   info    → en curso: alguien trabaja en ello y nadie está atrasado.
#   success → terminado con resultado positivo o verificado.
#   neutral → sin iniciar, inactivo, archivado o sin nada que reportar. (contorno)
# El color lo deciden el tiempo y el resultado; el paso del flujo se lee en el ícono y la palabra.
TONES = ("danger", "warning", "info", "success", "neutral")

# Familia de estados → valor → (tono, ícono). Las etiquetas salen siempre del modelo.
STATUS_STYLES = {
    "case": {
        "draft": ("neutral", "edit"),
        "pending_publication": ("info", "clock"),
        "published": ("info", "send"),
        "in_response": ("info", "pending"),
        "under_review": ("info", "search"),
        "correction_required": ("warning", "edit"),
        "pending_closure": ("info", "decision"),
        "closed": ("success", "check"),
    },
    "recommendation": {
        "pending": ("neutral", "pending"),
        "submitted": ("info", "send"),
        "under_review": ("info", "search"),
        "correction_required": ("warning", "edit"),
        "complied": ("success", "check"),
        "partial": ("warning", "half"),
        "not_complied": ("danger", "close"),
    },
    "inquiry": {
        "open": ("info", "message"),
        "in_progress": ("info", "user"),
        "waiting_institution": ("warning", "message"),
        "answered": ("success", "message"),
        "reopened": ("info", "back"),
        "closed": ("neutral", "check"),
    },
    "support": {
        "open": ("info", "message"),
        "in_progress": ("info", "user"),
        "resolved": ("success", "check"),
        "closed": ("neutral", "check"),
    },
    "decision": {
        "pending": ("info", "clock"),
        "approved": ("success", "check"),
        "returned": ("warning", "back"),
    },
    "document": {
        "historical": ("neutral", "history"),
        "draft": ("neutral", "edit"),
        "pending_approval": ("info", "clock"),
        "approved": ("success", "check"),
        "returned": ("warning", "back"),
    },
    "review_outcome": {
        "correction_required": ("warning", "edit"),
        "complied": ("success", "check"),
        "partial": ("warning", "half"),
        "not_complied": ("danger", "close"),
    },
}

# Gravedad (riesgo de hallazgos y nivel de atención de centros): otra forma (píldora con barras) y una escala de 4.
SEVERITY_LEVELS = {
    "risk": {"critical": 4, "high": 3, "medium": 2, "low": 1},
    "attention": {"immediate": 4, "high": 3, "followup": 2, "stable": 1},
}
SEVERITY_TONES = {4: "danger", 3: "danger-soft", 2: "warning", 1: "neutral"}

# Una decisión de Dirección pendiente pasa a «requiere atención» después de estos días.
DECISION_WAIT_WARNING_DAYS = 7


def _status_labels(family):
    from apps.accounts.models import TechnicalSupportRequest
    from apps.audits.models import AuditCase, AuditDocument, AuditInquiry, CaseDecision, Recommendation, Review

    choices = {
        "case": AuditCase.Status,
        "recommendation": Recommendation.Status,
        "inquiry": AuditInquiry.Status,
        "support": TechnicalSupportRequest.Status,
        "decision": CaseDecision.Status,
        "document": AuditDocument.Status,
        "review_outcome": Review.Outcome,
    }[family]
    return dict(choices.choices)


def status_style(family, status):
    """Devuelve el tono, el ícono y la etiqueta oficial de un estado."""
    tone, icon = STATUS_STYLES[family].get(status, ("neutral", "pending"))
    label = _status_labels(family).get(status, status)
    return {"tone": tone, "icon": icon, "label": label}


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
        return {"tone": "warning", "icon": "alert", "label": "Vence hoy"}
    tone = "warning" if deadline <= today + timedelta(days=DUE_SOON_DAYS) else "neutral"
    return {"tone": tone, "icon": "clock", "label": f"Vence el {short_date(deadline, today)}"}


@register.inclusion_tag("includes/ui/icon.html")
def ui_icon(name):
    return {"name": name}


@register.inclusion_tag("includes/ui/chip.html")
def ui_chip(tone, icon, label):
    """Chip de estado ad hoc (cuentas, CDE, verificaciones): siempre color, ícono y palabra."""
    return {"tone": tone if tone in TONES else "neutral", "icon": icon, "label": label}


@register.inclusion_tag("includes/ui/chip.html")
def ui_state_chip(family, status):
    return status_style(family, status)


@register.filter
def ui_tone(status, family):
    """Tono de un estado para avisos y barras: {{ review.outcome|ui_tone:"review_outcome" }}."""
    return STATUS_STYLES[family].get(status, ("neutral", "pending"))[0]


@register.inclusion_tag("includes/ui/chip.html")
def ui_status_chip(status, label=None):
    style = status_style("recommendation", status)
    if label:
        style["label"] = label
    return style


@register.inclusion_tag("includes/ui/chip.html")
def ui_case_status_chip(status):
    return status_style("case", status)


def severity_style(kind, value, label, muted=False):
    level = SEVERITY_LEVELS[kind].get(value, 1)
    tone = "neutral" if muted else SEVERITY_TONES[level]
    return {"level": level, "tone": tone, "label": label}


@register.filter
def ui_severity_tone(value, kind):
    """Tono de un nivel de gravedad para barras: {{ row.value|ui_severity_tone:"risk" }}."""
    return SEVERITY_TONES[SEVERITY_LEVELS[kind].get(value, 1)]


@register.inclusion_tag("includes/ui/severity_chip.html")
def ui_risk_chip(finding, muted=False):
    label = f"Riesgo {finding.get_risk_level_display().lower()}"
    return severity_style("risk", finding.risk_level, label, muted)


@register.inclusion_tag("includes/ui/severity_chip.html")
def ui_attention_chip(level, label):
    return severity_style("attention", level, label)


@register.inclusion_tag("includes/ui/chip.html")
def ui_wait_chip(since, now=None):
    """Tiempo de espera de una decisión de Dirección: en curso, o requiere atención si se alarga."""
    now = now or timezone.now()
    tone = "warning" if since and now - since > timedelta(days=DECISION_WAIT_WARNING_DAYS) else "info"
    return {"tone": tone, "icon": "clock", "label": f"Espera desde hace {timesince(since, now).split(',')[0]}"}


@register.inclusion_tag("includes/ui/chip.html")
def ui_deadline_chip(deadline):
    state = deadline_state(deadline)
    if state is None:
        return {"tone": "neutral", "icon": "clock", "label": "Sin fecha límite"}
    return state


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


AVATAR_SIZES = {"xs", "sm", "md", "lg", "xl"}


@register.inclusion_tag("includes/ui/avatar.html", takes_context=True)
def ui_avatar(context, person, size="md"):
    """Foto de perfil o iniciales. Es decorativa: el nombre siempre va junto a ella."""
    from django.urls import reverse

    from apps.accounts.avatars import user_can_view_avatar

    viewer = context.get("user")
    url = ""
    if person and getattr(person, "avatar", None) and viewer is not None and user_can_view_avatar(viewer, person):
        version = int(person.avatar_updated_at.timestamp()) if person.avatar_updated_at else 0
        url = f"{reverse('user_avatar', args=[person.pk])}?v={version}"
    return {
        "url": url,
        "initials": person.initials if person else "?",
        "size": size if size in AVATAR_SIZES else "md",
    }
