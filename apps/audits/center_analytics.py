from datetime import timedelta

from django.db.models import (
    Count,
    DateField,
    DateTimeField,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.institutions.models import Organization, SchoolBoardPeriod

from .models import AuditCase, Finding, Recommendation, Response, Review
from .services import with_effective_deadline
from .statistics import RESPONSE_DUE_STATUSES, TERMINAL_RECOMMENDATION_STATUSES


CONSOLIDATED_CASE_STATUSES = (
    AuditCase.Status.PUBLISHED,
    AuditCase.Status.IN_RESPONSE,
    AuditCase.Status.UNDER_REVIEW,
    AuditCase.Status.CORRECTION_REQUIRED,
    AuditCase.Status.PENDING_CLOSURE,
    AuditCase.Status.CLOSED,
)

ACTIVE_CASE_STATUSES = (
    AuditCase.Status.PUBLISHED,
    AuditCase.Status.IN_RESPONSE,
    AuditCase.Status.UNDER_REVIEW,
    AuditCase.Status.CORRECTION_REQUIRED,
    AuditCase.Status.PENDING_CLOSURE,
)


def _count_for_organization(queryset, group_field):
    grouped = (
        queryset.order_by()
        .values(group_field)
        .annotate(total=Count("pk", distinct=True))
        .values("total")[:1]
    )
    return Coalesce(
        Subquery(grouped, output_field=IntegerField()),
        Value(0),
    )


def center_analytics_queryset(today=None):
    """Return every educational center with institutional intelligence annotations.

    Audit subject indicators are attributed through ``audited_organization`` while
    response and compliance indicators are attributed through
    ``responsible_organization``. Draft and unpublished cases are intentionally
    excluded from consolidated institutional indicators.
    """

    today = today or timezone.localdate()
    due_soon_limit = today + timedelta(days=7)

    institutional_users = User.objects.filter(
        organization_id=OuterRef("pk"),
        role=User.Role.INSTITUTION,
    )
    active_institutional_users = institutional_users.filter(is_active=True)

    marked_cde = SchoolBoardPeriod.objects.filter(
        organization_id=OuterRef("pk"),
        is_current=True,
    ).order_by("-start_date", "-pk")
    valid_current_cde = marked_cde.filter(
        start_date__lte=today,
        end_date__gte=today,
    )

    audited_cases = AuditCase.objects.filter(
        audited_organization_id=OuterRef("pk"),
        status__in=CONSOLIDATED_CASE_STATUSES,
    )
    active_audited_cases = audited_cases.filter(status__in=ACTIVE_CASE_STATUSES)
    provisional_cases = AuditCase.objects.filter(
        audited_organization_id=OuterRef("pk"),
        status__in=[AuditCase.Status.DRAFT, AuditCase.Status.PENDING_PUBLICATION],
    )

    consolidated_findings = Finding.objects.filter(
        case__audited_organization_id=OuterRef("pk"),
        case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    active_findings = consolidated_findings.filter(case__status__in=ACTIVE_CASE_STATUSES)

    obligations = Recommendation.objects.filter(
        responsible_organization_id=OuterRef("pk"),
        finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    obligations_with_deadline = with_effective_deadline(obligations)
    terminal_obligations = obligations.filter(
        status__in=TERMINAL_RECOMMENDATION_STATUSES
    )
    open_overdue = obligations_with_deadline.filter(
        current_deadline__lt=today,
        status__in=RESPONSE_DUE_STATUSES,
    )
    due_soon = obligations_with_deadline.filter(
        current_deadline__gte=today,
        current_deadline__lte=due_soon_limit,
        status__in=RESPONSE_DUE_STATUSES,
    )

    responses = Response.objects.filter(
        recommendation__responsible_organization_id=OuterRef("pk"),
        recommendation__finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    reviews = Review.objects.filter(
        response__recommendation__responsible_organization_id=OuterRef("pk"),
        response__recommendation__finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )

    return Organization.objects.filter(
        kind=Organization.Kind.EDUCATIONAL_CENTER
    ).annotate(
        active_user_count=_count_for_organization(
            active_institutional_users, "organization_id"
        ),
        institutional_user_count=_count_for_organization(
            institutional_users, "organization_id"
        ),
        last_institutional_login=Subquery(
            institutional_users.order_by("-last_login")
            .exclude(last_login__isnull=True)
            .values("last_login")[:1],
            output_field=DateTimeField(),
        ),
        cde_start_date=Subquery(
            marked_cde.values("start_date")[:1], output_field=DateField()
        ),
        cde_end_date=Subquery(
            marked_cde.values("end_date")[:1], output_field=DateField()
        ),
        has_current_cde=Exists(valid_current_cde),
        case_count=_count_for_organization(
            audited_cases, "audited_organization_id"
        ),
        active_case_count=_count_for_organization(
            active_audited_cases, "audited_organization_id"
        ),
        closed_case_count=_count_for_organization(
            audited_cases.filter(status=AuditCase.Status.CLOSED),
            "audited_organization_id",
        ),
        provisional_case_count=_count_for_organization(
            provisional_cases, "audited_organization_id"
        ),
        latest_case_activity=Subquery(
            audited_cases.order_by("-updated_at").values("updated_at")[:1],
            output_field=DateTimeField(),
        ),
        latest_report_date=Subquery(
            audited_cases.exclude(report_date__isnull=True)
            .order_by("-report_date", "-pk")
            .values("report_date")[:1],
            output_field=DateField(),
        ),
        finding_count=_count_for_organization(
            consolidated_findings, "case__audited_organization_id"
        ),
        critical_active_count=_count_for_organization(
            active_findings.filter(risk_level=Finding.RiskLevel.CRITICAL),
            "case__audited_organization_id",
        ),
        high_active_count=_count_for_organization(
            active_findings.filter(risk_level=Finding.RiskLevel.HIGH),
            "case__audited_organization_id",
        ),
        obligation_count=_count_for_organization(
            obligations, "responsible_organization_id"
        ),
        terminal_count=_count_for_organization(
            terminal_obligations, "responsible_organization_id"
        ),
        complied_count=_count_for_organization(
            terminal_obligations.filter(status=Recommendation.Status.COMPLIED),
            "responsible_organization_id",
        ),
        partial_count=_count_for_organization(
            terminal_obligations.filter(status=Recommendation.Status.PARTIAL),
            "responsible_organization_id",
        ),
        not_complied_count=_count_for_organization(
            terminal_obligations.filter(status=Recommendation.Status.NOT_COMPLIED),
            "responsible_organization_id",
        ),
        pending_count=_count_for_organization(
            obligations.filter(status=Recommendation.Status.PENDING),
            "responsible_organization_id",
        ),
        submitted_count=_count_for_organization(
            obligations.filter(status=Recommendation.Status.SUBMITTED),
            "responsible_organization_id",
        ),
        under_review_count=_count_for_organization(
            obligations.filter(status=Recommendation.Status.UNDER_REVIEW),
            "responsible_organization_id",
        ),
        correction_count=_count_for_organization(
            obligations.filter(status=Recommendation.Status.CORRECTION_REQUIRED),
            "responsible_organization_id",
        ),
        automatic_no_response_count=_count_for_organization(
            obligations.exclude(no_response_recorded_at__isnull=True),
            "responsible_organization_id",
        ),
        explicit_followup_count=_count_for_organization(
            obligations.filter(
                Q(source_recommendation__isnull=False) | Q(carried_from__isnull=False)
            ),
            "responsible_organization_id",
        ),
        overdue_count=_count_for_organization(
            open_overdue, "responsible_organization_id"
        ),
        due_soon_count=_count_for_organization(
            due_soon, "responsible_organization_id"
        ),
        pending_review_count=_count_for_organization(
            responses.filter(review__isnull=True),
            "recommendation__responsible_organization_id",
        ),
        response_count=_count_for_organization(
            responses, "recommendation__responsible_organization_id"
        ),
        latest_response_at=Subquery(
            responses.order_by("-submitted_at").values("submitted_at")[:1],
            output_field=DateTimeField(),
        ),
        latest_review_at=Subquery(
            reviews.order_by("-reviewed_at").values("reviewed_at")[:1],
            output_field=DateTimeField(),
        ),
    )


def enrich_center(center, today=None):
    """Attach display-only values without hiding the underlying reasons."""

    today = today or timezone.localdate()
    center.compliance_rate = (
        round((center.complied_count / center.terminal_count) * 100)
        if center.terminal_count
        else None
    )
    center.access_active = bool(center.is_active and center.active_user_count)
    accounts = getattr(center, "institutional_accounts", [])
    center.activation_pending = any(account.activation_requested_at for account in accounts)
    center.access_label = (
        "Activo" if center.access_active else
        "Pendiente de establecer contraseña" if center.activation_pending else
        "Suspendido" if center.institutional_user_count else "Sin activar"
    )

    if center.has_current_cde:
        center.cde_state = "current"
        center.cde_state_label = "CDE vigente"
    elif center.cde_start_date and center.cde_start_date > today:
        center.cde_state = "future"
        center.cde_state_label = "CDE aún no inicia"
    elif center.cde_end_date and center.cde_end_date < today:
        center.cde_state = "expired"
        center.cde_state_label = "CDE vencido"
    else:
        center.cde_state = "missing"
        center.cde_state_label = "Sin CDE vigente"

    activity_dates = [
        value
        for value in (
            center.latest_case_activity,
            center.latest_response_at,
            center.latest_review_at,
        )
        if value is not None
    ]
    center.latest_activity_at = max(activity_dates) if activity_dates else None

    reasons = []
    if center.overdue_count:
        reasons.append(
            {
                "kind": "immediate",
                "label": f"{center.overdue_count} obligación(es) vencida(s)",
            }
        )
    if center.critical_active_count:
        reasons.append(
            {
                "kind": "immediate",
                "label": f"{center.critical_active_count} hallazgo(s) crítico(s) activo(s)",
            }
        )
    if center.automatic_no_response_count:
        reasons.append(
            {
                "kind": "high",
                "label": f"{center.automatic_no_response_count} incumplimiento(s) automático(s)",
            }
        )
    if center.correction_count:
        reasons.append(
            {
                "kind": "high",
                "label": f"{center.correction_count} respuesta(s) por corregir",
            }
        )
    if center.high_active_count:
        reasons.append(
            {
                "kind": "high",
                "label": f"{center.high_active_count} hallazgo(s) de riesgo alto activo(s)",
            }
        )
    if center.due_soon_count:
        reasons.append(
            {
                "kind": "followup",
                "label": f"{center.due_soon_count} obligación(es) vence(n) en 7 días",
            }
        )
    if center.obligation_count and not center.access_active:
        reasons.append({"kind": "followup", "label": "Obligaciones sin acceso activo"})
    if center.obligation_count and not center.has_current_cde:
        reasons.append({"kind": "followup", "label": center.cde_state_label})

    center.attention_reasons = reasons
    if any(reason["kind"] == "immediate" for reason in reasons):
        center.attention_level = "immediate"
        center.attention_label = "Atención inmediata"
    elif any(reason["kind"] == "high" for reason in reasons):
        center.attention_level = "high"
        center.attention_label = "Prioridad alta"
    elif reasons:
        center.attention_level = "followup"
        center.attention_label = "Seguimiento"
    else:
        center.attention_level = "stable"
        center.attention_label = "Sin alertas actuales"
    return center


def enrich_centers(centers, today=None):
    today = today or timezone.localdate()
    return [enrich_center(center, today=today) for center in centers]
