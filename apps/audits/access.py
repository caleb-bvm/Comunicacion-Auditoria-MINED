"""Alcance de consulta del equipo auditor.

Cada expediente tiene un auditor responsable, el único que actúa sobre él (borrador,
revisiones, prórrogas, cierre, consultas). El resto del equipo puede consultarlo en modo
de solo lectura una vez publicado, salvo que Dirección lo haya reservado."""

from django.db.models import Q

from .models import AuditCase

# Expedientes oficiales: aprobados por Dirección y enviados a las instituciones.
TEAM_VISIBLE_STATUSES = (
    AuditCase.Status.PUBLISHED,
    AuditCase.Status.IN_RESPONSE,
    AuditCase.Status.UNDER_REVIEW,
    AuditCase.Status.CORRECTION_REQUIRED,
    AuditCase.Status.PENDING_CLOSURE,
    AuditCase.Status.CLOSED,
)


def team_visible_q(prefix=""):
    """Condición de expediente consultable por todo el equipo auditor."""
    return Q(**{f"{prefix}status__in": TEAM_VISIBLE_STATUSES, f"{prefix}is_reserved": False})


def auditor_viewable_q(user, prefix=""):
    """Expedientes que un auditor puede consultar: los suyos y los del equipo."""
    return Q(**{f"{prefix}assigned_auditor": user}) | team_visible_q(prefix)


def is_team_visible(case):
    return case.status in TEAM_VISIBLE_STATUSES and not case.is_reserved
