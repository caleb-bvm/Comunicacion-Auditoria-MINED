from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.models import User
from apps.institutions.models import Organization

from .center_analytics import (
    CONSOLIDATED_CASE_STATUSES,
    center_analytics_queryset,
    enrich_centers,
)
from .models import (
    AuditCase,
    DeadlineExtension,
    Finding,
    Recommendation,
    Response,
    Review,
)


PERIOD_CHOICES = (
    ("year", "Año actual"),
    ("30", "Últimos 30 días"),
    ("90", "Últimos 90 días"),
    ("previous_year", "Año anterior"),
    ("all", "Todo el historial"),
    ("custom", "Rango personalizado"),
)

GROUP_CHOICES = (
    ("department", "Departamento"),
    ("district", "Distrito"),
)

QUICK_FILTER_DEFINITIONS = (
    {
        "value": "immediate",
        "label": "Atención inmediata",
        "description": "Vencimientos o riesgo crítico",
        "tone": "danger",
    },
    {
        "value": "overdue",
        "label": "Plazos vencidos",
        "description": "Obligaciones abiertas fuera de plazo",
        "tone": "danger",
    },
    {
        "value": "critical",
        "label": "Riesgo crítico",
        "description": "Hallazgos críticos en expedientes activos",
        "tone": "danger",
    },
    {
        "value": "not_complied",
        "label": "Incumplimientos",
        "description": "Recomendaciones declaradas no cumplidas",
        "tone": "danger",
    },
    {
        "value": "correction",
        "label": "Por corregir",
        "description": "Respuestas devueltas por Auditoría",
        "tone": "warning",
    },
    {
        "value": "due_soon",
        "label": "Vencen en 7 días",
        "description": "Seguimiento preventivo de plazos",
        "tone": "warning",
    },
    {
        "value": "never_audited",
        "label": "Nunca auditados",
        "description": "Brechas de cobertura institucional",
        "tone": "neutral",
    },
)


def _date_value(raw_value):
    try:
        return date.fromisoformat(raw_value) if raw_value else None
    except ValueError:
        return None


def _period_dates(params, today):
    valid_periods = {value for value, _label in PERIOD_CHOICES}
    period = params.get("period", "year")
    errors = []
    if period not in valid_periods:
        period = "year"

    start_date = end_date = None
    if period == "year":
        start_date = date(today.year, 1, 1)
        end_date = today
    elif period == "30":
        start_date = today - timedelta(days=29)
        end_date = today
    elif period == "90":
        start_date = today - timedelta(days=89)
        end_date = today
    elif period == "previous_year":
        start_date = date(today.year - 1, 1, 1)
        end_date = date(today.year - 1, 12, 31)
    elif period == "custom":
        start_date = _date_value(params.get("start"))
        end_date = _date_value(params.get("end"))
        if not start_date or not end_date:
            errors.append("Indique una fecha inicial y una fecha final válidas.")
        elif start_date > end_date:
            errors.append("La fecha inicial no puede ser posterior a la fecha final.")

    return period, start_date, end_date, errors


def _rate(part, total):
    return round((part / total) * 100) if total else 0


def _nullable_rate(part, total):
    return round((part / total) * 100) if total else None


def _geography_options(params):
    centers = Organization.objects.filter(kind=Organization.Kind.EDUCATIONAL_CENTER)
    departments = list(
        centers.exclude(department="")
        .values_list("department", flat=True)
        .distinct()
        .order_by("department")
    )
    selected_department = params.get("department", "").strip()
    districts = []
    if hasattr(Organization, "district"):
        district_queryset = centers
        if selected_department:
            district_queryset = district_queryset.filter(department=selected_department)
        districts = list(
            district_queryset.exclude(district="")
            .values_list("district", flat=True)
            .distinct()
            .order_by("district")
        )
    return departments, districts


def _matches_center_filters(center, filters):
    quick_filter = filters["selected_quick_filter"]
    if quick_filter == "immediate" and center.attention_level != "immediate":
        return False
    if quick_filter == "overdue" and not center.overdue_count:
        return False
    if quick_filter == "critical" and not center.critical_active_count:
        return False
    if quick_filter == "not_complied" and not center.not_complied_count:
        return False
    if quick_filter == "correction" and not center.correction_count:
        return False
    if quick_filter == "due_soon" and not center.due_soon_count:
        return False
    if quick_filter == "never_audited" and center.case_count:
        return False

    attention = filters["selected_attention"]
    if attention and center.attention_level != attention:
        return False

    coverage = filters["selected_coverage"]
    if coverage == "audited" and not center.case_count:
        return False
    if coverage == "not_audited" and center.case_count:
        return False

    risk = filters["selected_risk"]
    if risk == "critical" and not center.critical_active_count:
        return False
    if risk == "high" and not (
        center.critical_active_count or center.high_active_count
    ):
        return False

    cde = filters["selected_cde"]
    if cde == "current" and not center.has_current_cde:
        return False
    if cde == "pending" and center.has_current_cde:
        return False

    access = filters["selected_access"]
    if access == "active" and not center.access_active:
        return False
    if access == "pending" and center.access_active:
        return False

    compliance = filters["selected_compliance"]
    if compliance == "not_available" and center.compliance_rate is not None:
        return False
    if compliance == "low" and not (
        center.compliance_rate is not None and center.compliance_rate < 50
    ):
        return False
    if compliance == "medium" and not (
        center.compliance_rate is not None and 50 <= center.compliance_rate < 80
    ):
        return False
    if compliance == "high" and not (
        center.compliance_rate is not None and 80 <= center.compliance_rate < 100
    ):
        return False
    if compliance == "complete" and center.compliance_rate != 100:
        return False
    return True


def _quick_filter_matches(center, value):
    if value == "immediate":
        return center.attention_level == "immediate"
    if value == "overdue":
        return bool(center.overdue_count)
    if value == "critical":
        return bool(center.critical_active_count)
    if value == "not_complied":
        return bool(center.not_complied_count)
    if value == "correction":
        return bool(center.correction_count)
    if value == "due_soon":
        return bool(center.due_soon_count)
    if value == "never_audited":
        return not center.case_count
    return True


def _quick_filters(centers, filters):
    query_params = {
        "mode": "current",
        "department": filters["selected_department"],
        "district": filters["selected_district"],
        "group_by": filters["selected_group_by"],
        "period": filters["selected_period"],
    }
    if filters["selected_period"] == "custom":
        if filters["start_date"]:
            query_params["start"] = filters["start_date"].isoformat()
        if filters["end_date"]:
            query_params["end"] = filters["end_date"].isoformat()

    has_complex_condition = any(
        filters[name]
        for name in (
            "selected_attention",
            "selected_coverage",
            "selected_risk",
            "selected_cde",
            "selected_access",
            "selected_compliance",
        )
    )
    rows = [
        {
            "value": "",
            "label": "Vista general",
            "description": "Todos los centros del territorio",
            "tone": "neutral",
            "count": len(centers),
            "url": f"?{urlencode(query_params)}",
            "is_active": not filters["selected_quick_filter"]
            and not has_complex_condition,
        }
    ]
    for definition in QUICK_FILTER_DEFINITIONS:
        shortcut_params = {**query_params, "quick": definition["value"]}
        rows.append(
            {
                **definition,
                "count": sum(
                    _quick_filter_matches(center, definition["value"])
                    for center in centers
                ),
                "url": f"?{urlencode(shortcut_params)}",
                "is_active": filters["selected_quick_filter"]
                == definition["value"],
            }
        )
    return rows


def _territory_label(field):
    return dict(GROUP_CHOICES).get(field, "Territorio")


def _territory_rows(centers, group_by):
    grouped = defaultdict(list)
    for center in centers:
        value = getattr(center, group_by, "") or ""
        grouped[value].append(center)

    rows = []
    for value, territory_centers in grouped.items():
        center_count = len(territory_centers)
        audited_count = sum(bool(center.case_count) for center in territory_centers)
        immediate_count = sum(
            center.attention_level == "immediate" for center in territory_centers
        )
        high_attention_count = sum(
            center.attention_level == "high" for center in territory_centers
        )
        overdue_center_count = sum(
            bool(center.overdue_count) for center in territory_centers
        )
        critical_center_count = sum(
            bool(center.critical_active_count) for center in territory_centers
        )
        terminal_count = sum(center.terminal_count for center in territory_centers)
        complied_count = sum(center.complied_count for center in territory_centers)
        rows.append(
            {
                "value": value,
                "name": value or f"Sin {_territory_label(group_by).lower()} registrado",
                "center_count": center_count,
                "audited_count": audited_count,
                "coverage_rate": _rate(audited_count, center_count),
                "immediate_count": immediate_count,
                "immediate_rate": _rate(immediate_count, center_count),
                "high_attention_count": high_attention_count,
                "overdue_center_count": overdue_center_count,
                "critical_center_count": critical_center_count,
                "without_cde_count": sum(
                    not center.has_current_cde for center in territory_centers
                ),
                "without_access_count": sum(
                    bool(center.obligation_count and not center.access_active)
                    for center in territory_centers
                ),
                "case_count": sum(center.case_count for center in territory_centers),
                "obligation_count": sum(
                    center.obligation_count for center in territory_centers
                ),
                "overdue_count": sum(
                    center.overdue_count for center in territory_centers
                ),
                "terminal_count": terminal_count,
                "complied_count": complied_count,
                "compliance_rate": _nullable_rate(complied_count, terminal_count),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -row["immediate_count"],
            -row["overdue_center_count"],
            -row["critical_center_count"],
            row["name"],
        ),
    )


def _distribution_rows(centers):
    total = len(centers)
    attention_definitions = (
        ("immediate", "Atención inmediata"),
        ("high", "Prioridad alta"),
        ("followup", "Seguimiento"),
        ("stable", "Sin alertas actuales"),
    )
    attention = []
    for value, label in attention_definitions:
        count = sum(center.attention_level == value for center in centers)
        attention.append(
            {"value": value, "label": label, "count": count, "percentage": _rate(count, total)}
        )

    coverage = []
    for value, label, predicate in (
        ("audited", "Con auditorías consolidadas", lambda center: center.case_count > 0),
        ("not_audited", "Sin auditorías consolidadas", lambda center: center.case_count == 0),
    ):
        count = sum(predicate(center) for center in centers)
        coverage.append(
            {"value": value, "label": label, "count": count, "percentage": _rate(count, total)}
        )

    cde = []
    for value, label, predicate in (
        ("current", "CDE vigente", lambda center: center.cde_state == "current"),
        ("expired", "CDE vencido", lambda center: center.cde_state == "expired"),
        ("future", "CDE aún no inicia", lambda center: center.cde_state == "future"),
        ("missing", "Sin período vigente", lambda center: center.cde_state == "missing"),
    ):
        count = sum(predicate(center) for center in centers)
        cde.append(
            {"value": value, "label": label, "count": count, "percentage": _rate(count, total)}
        )

    compliance_definitions = (
        ("not_available", "Sin resultados definitivos", lambda value: value is None),
        ("low", "Menos de 50%", lambda value: value is not None and value < 50),
        ("medium", "50% a 79%", lambda value: value is not None and 50 <= value < 80),
        ("high", "80% a 99%", lambda value: value is not None and 80 <= value < 100),
        ("complete", "100%", lambda value: value == 100),
    )
    compliance = []
    for value, label, predicate in compliance_definitions:
        count = sum(predicate(center.compliance_rate) for center in centers)
        compliance.append(
            {"value": value, "label": label, "count": count, "percentage": _rate(count, total)}
        )

    risk = []
    for value, label, predicate in (
        ("critical", "Con riesgo crítico activo", lambda center: center.critical_active_count > 0),
        (
            "high",
            "Con riesgo alto, sin crítico",
            lambda center: not center.critical_active_count and center.high_active_count > 0,
        ),
        (
            "no_high_risk",
            "Sin riesgo alto o crítico activo",
            lambda center: not center.critical_active_count and not center.high_active_count,
        ),
    ):
        count = sum(predicate(center) for center in centers)
        risk.append(
            {"value": value, "label": label, "count": count, "percentage": _rate(count, total)}
        )

    obligation_statuses = (
        ("pending", "Pendientes", "pending_count"),
        ("submitted", "Respuesta enviada", "submitted_count"),
        ("under_review", "En revisión", "under_review_count"),
        ("correction_required", "Requieren corrección", "correction_count"),
        ("complied", "Cumplidas", "complied_count"),
        ("partial", "Parcialmente cumplidas", "partial_count"),
        ("not_complied", "No cumplidas", "not_complied_count"),
    )
    obligation_total = sum(center.obligation_count for center in centers)
    obligation_distribution = []
    for value, label, attribute in obligation_statuses:
        count = sum(getattr(center, attribute) for center in centers)
        obligation_distribution.append(
            {
                "value": value,
                "label": label,
                "count": count,
                "percentage": _rate(count, obligation_total),
            }
        )

    return {
        "attention_distribution": attention,
        "coverage_distribution": coverage,
        "cde_distribution": cde,
        "compliance_distribution": compliance,
        "risk_distribution": risk,
        "obligation_distribution": obligation_distribution,
    }


def _monthly_activity(cases, responses, reviews):
    rows = defaultdict(lambda: {"cases": 0, "responses": 0, "reviews": 0})
    for item in (
        cases.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("pk"))
    ):
        if item["month"]:
            rows[item["month"].date().replace(day=1)]["cases"] = item["total"]
    for item in (
        responses.annotate(month=TruncMonth("submitted_at"))
        .values("month")
        .annotate(total=Count("pk"))
    ):
        if item["month"]:
            rows[item["month"].date().replace(day=1)]["responses"] = item["total"]
    for item in (
        reviews.annotate(month=TruncMonth("reviewed_at"))
        .values("month")
        .annotate(total=Count("pk"))
    ):
        if item["month"]:
            rows[item["month"].date().replace(day=1)]["reviews"] = item["total"]

    result = []
    for month, values in sorted(rows.items())[-12:]:
        result.append({"month": month, **values})
    maximum = max(
        (max(row["cases"], row["responses"], row["reviews"]) for row in result),
        default=1,
    )
    return result, maximum


def build_territorial_analysis(params, today=None):
    """Build the shared dataset for the web analysis and its future XLSX export."""

    today = today or timezone.localdate()
    selected_mode = params.get("mode", "current")
    if selected_mode not in {"current", "activity"}:
        selected_mode = "current"

    period, start_date, end_date, errors = _period_dates(params, today)
    if selected_mode == "current":
        # The current snapshot deliberately uses the complete consolidated history.
        # Period validation belongs only to the activity view.
        errors = []
    departments, districts = _geography_options(params)

    if params.get("department"):
        default_group = "district"
    else:
        default_group = "department"

    selected_group = params.get("group_by", "")
    valid_groups = {value for value, _label in GROUP_CHOICES}
    if selected_group not in valid_groups:
        selected_group = default_group

    selected_quick_filter = params.get("quick", "")
    valid_quick_filters = {
        definition["value"] for definition in QUICK_FILTER_DEFINITIONS
    }
    if selected_quick_filter not in valid_quick_filters:
        selected_quick_filter = ""

    advanced_filter_count = sum(
        bool(params.get(name, "").strip())
        for name in ("coverage", "risk", "cde", "access", "compliance")
    )
    advanced_filter_count += selected_group != default_group

    filters = {
        "selected_mode": selected_mode,
        "selected_period": period,
        "selected_period_label": dict(PERIOD_CHOICES)[period],
        "start_date": start_date,
        "end_date": end_date,
        "selected_department": params.get("department", "").strip(),
        "selected_district": params.get("district", "").strip(),
        "selected_group_by": selected_group,
        "selected_group_label": _territory_label(selected_group),
        "selected_quick_filter": selected_quick_filter,
        "selected_attention": params.get("attention", ""),
        "selected_coverage": params.get("coverage", ""),
        "selected_risk": params.get("risk", ""),
        "selected_cde": params.get("cde", ""),
        "selected_access": params.get("access", ""),
        "selected_compliance": params.get("compliance", ""),
        "filter_errors": errors,
        "advanced_filter_count": advanced_filter_count,
        "advanced_filters_open": bool(advanced_filter_count),
    }

    center_queryset = center_analytics_queryset(today=today)
    if filters["selected_department"]:
        center_queryset = center_queryset.filter(
            department=filters["selected_department"]
        )
    if filters["selected_district"] and hasattr(Organization, "district"):
        center_queryset = center_queryset.filter(district=filters["selected_district"])

    scoped_centers = enrich_centers(list(center_queryset), today=today)
    quick_filters = _quick_filters(scoped_centers, filters)
    centers = [
        center for center in scoped_centers if _matches_center_filters(center, filters)
    ]
    center_ids = [center.pk for center in centers]
    center_count = len(centers)
    audited_center_count = sum(bool(center.case_count) for center in centers)
    immediate_center_count = sum(
        center.attention_level == "immediate" for center in centers
    )
    terminal_count = sum(center.terminal_count for center in centers)
    complied_count = sum(center.complied_count for center in centers)

    priority_centers = sorted(
        (center for center in centers if center.attention_reasons),
        key=lambda center: (
            -center.overdue_count,
            -center.critical_active_count,
            -center.automatic_no_response_count,
            -center.correction_count,
            -center.due_soon_count,
            -center.high_active_count,
            center.name,
        ),
    )[:12]

    cases = AuditCase.objects.filter(
        audited_organization_id__in=center_ids,
        status__in=CONSOLIDATED_CASE_STATUSES,
    )
    responses = Response.objects.filter(
        recommendation__responsible_organization_id__in=center_ids,
        recommendation__finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    reviews = Review.objects.filter(
        response__recommendation__responsible_organization_id__in=center_ids,
        response__recommendation__finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    extensions = DeadlineExtension.objects.filter(
        recommendation__responsible_organization_id__in=center_ids,
        recommendation__finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
    )
    automatic_no_response = Recommendation.objects.filter(
        responsible_organization_id__in=center_ids,
        finding__case__status__in=CONSOLIDATED_CASE_STATUSES,
        no_response_recorded_at__isnull=False,
    )
    reports_issued = cases.exclude(report_date__isnull=True)
    if errors:
        cases = cases.none()
        responses = responses.none()
        reviews = reviews.none()
        extensions = extensions.none()
        automatic_no_response = automatic_no_response.none()
        reports_issued = reports_issued.none()
    elif start_date and end_date and start_date <= end_date:
        cases = cases.filter(created_at__date__range=(start_date, end_date))
        responses = responses.filter(submitted_at__date__range=(start_date, end_date))
        reviews = reviews.filter(reviewed_at__date__range=(start_date, end_date))
        extensions = extensions.filter(granted_at__date__range=(start_date, end_date))
        automatic_no_response = automatic_no_response.filter(
            no_response_recorded_at__date__range=(start_date, end_date)
        )
        reports_issued = reports_issued.filter(
            report_date__range=(start_date, end_date)
        )

    activity_findings = Finding.objects.filter(case__in=cases)
    activity_recommendations = Recommendation.objects.filter(finding__case__in=cases)
    monthly_activity, monthly_activity_max = _monthly_activity(
        cases, responses, reviews
    )

    context = {
        **filters,
        "period_choices": PERIOD_CHOICES,
        "group_choices": GROUP_CHOICES,
        "department_options": departments,
        "district_options": districts,
        "district_supported": hasattr(Organization, "district"),
        "quick_filters": quick_filters,
        "centers": centers,
        "selected_center_ids": center_ids,
        "center_count": center_count,
        "audited_center_count": audited_center_count,
        "not_audited_center_count": center_count - audited_center_count,
        "coverage_rate": _rate(audited_center_count, center_count),
        "immediate_center_count": immediate_center_count,
        "overdue_center_count": sum(bool(center.overdue_count) for center in centers),
        "critical_center_count": sum(
            bool(center.critical_active_count) for center in centers
        ),
        "without_current_cde_count": sum(
            not center.has_current_cde for center in centers
        ),
        "without_access_count": sum(
            bool(center.obligation_count and not center.access_active)
            for center in centers
        ),
        "total_obligations": sum(center.obligation_count for center in centers),
        "overdue_obligations": sum(center.overdue_count for center in centers),
        "terminal_obligations": terminal_count,
        "complied_obligations": complied_count,
        "territorial_compliance_rate": _nullable_rate(
            complied_count, terminal_count
        ),
        "priority_centers": priority_centers,
        "territory_rows": _territory_rows(centers, selected_group),
        "activity_case_count": cases.count(),
        "activity_report_count": reports_issued.count(),
        "activity_finding_count": activity_findings.count(),
        "activity_critical_count": activity_findings.filter(
            risk_level=Finding.RiskLevel.CRITICAL
        ).count(),
        "activity_recommendation_count": activity_recommendations.count(),
        "activity_response_count": responses.count(),
        "activity_review_count": reviews.count(),
        "activity_extension_count": extensions.count(),
        "activity_automatic_no_response_count": automatic_no_response.count(),
        "monthly_activity": monthly_activity,
        "monthly_activity_max": monthly_activity_max,
        "never_audited_centers": sorted(
            (center for center in centers if not center.case_count),
            key=lambda center: (center.department, center.district, center.name),
        )[:12],
        "data_quality": {
            "without_department": sum(not center.department for center in centers),
            "without_district": (
                sum(not getattr(center, "district", "") for center in centers)
                if hasattr(Organization, "district")
                else center_count
            ),
        },
    }
    context.update(_distribution_rows(centers))
    return context
