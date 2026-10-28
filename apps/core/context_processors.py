from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.audits.models import AuditCase, CaseDecision


def _count_text(count, singular, plural):
    return ngettext(singular, plural, count) % {"count": count}


def sidebar_context(request):
    # Las páginas de error 400 pueden renderizarse antes de AuthenticationMiddleware.
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    if user.is_superuser or user.role == User.Role.TECHNICAL_ADMIN:
        active_users = User.objects.filter(is_active=True).count()
        context = {
            "label": "Administración del sistema",
            "value": _count_text(
                active_users,
                "%(count)d usuario activo",
                "%(count)d usuarios activos",
            ),
        }
    elif user.role == User.Role.AUDIT_MANAGER:
        pending_decisions = CaseDecision.objects.filter(
            status=CaseDecision.Status.PENDING
        ).count()
        context = {
            "label": "Decisiones pendientes",
            "value": _count_text(
                pending_decisions,
                "%(count)d decisión pendiente",
                "%(count)d decisiones pendientes",
            ),
        }
    elif user.role == User.Role.AUDITOR:
        assigned_organizations = (
            AuditCase.objects.filter(assigned_auditor=user)
            .values("audited_organization_id")
            .distinct()
            .count()
        )
        context = {
            "label": "Instituciones asignadas",
            "value": _count_text(
                assigned_organizations,
                "%(count)d institución",
                "%(count)d instituciones",
            ),
        }
    elif user.role == User.Role.INSTITUTION:
        context = None
    else:
        context = {
            "label": user.get_role_display(),
            "value": user.get_full_name() or user.username,
        }

    return {"sidebar_context": context}
