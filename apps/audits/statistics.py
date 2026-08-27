from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import AuditCase, Finding, Recommendation, Response
from .services import with_effective_deadline


TERMINAL_RECOMMENDATION_STATUSES = (
    Recommendation.Status.COMPLIED,
    Recommendation.Status.PARTIAL,
    Recommendation.Status.NOT_COMPLIED,
)
RESPONSE_DUE_STATUSES = (
    Recommendation.Status.PENDING,
    Recommendation.Status.CORRECTION_REQUIRED,
)


def percentage(part, total):
    return round((part / total) * 100) if total else 0


def distribution(queryset, field, choices):
    counts = dict(
        queryset.values(field)
        .annotate(total=Count("pk"))
        .values_list(field, "total")
    )
    total = sum(counts.values())
    return [
        {
            "value": value,
            "label": label,
            "count": counts.get(value, 0),
            "percentage": percentage(counts.get(value, 0), total),
        }
        for value, label in choices
        if counts.get(value, 0)
    ]


def build_case_statistics(cases, today=None):
    """Build a consistent statistical snapshot from an already-scoped case queryset."""
    today = today or timezone.localdate()
    recommendations = Recommendation.objects.filter(finding__case__in=cases)
    findings = Finding.objects.filter(case__in=cases)
    responses = Response.objects.filter(recommendation__in=recommendations)
    terminal_recommendations = recommendations.filter(
        status__in=TERMINAL_RECOMMENDATION_STATUSES
    )
    terminal_count = terminal_recommendations.count()
    complied_count = terminal_recommendations.filter(
        status=Recommendation.Status.COMPLIED
    ).count()
    overdue = with_effective_deadline(recommendations).filter(
        current_deadline__lt=today,
        status__in=RESPONSE_DUE_STATUSES,
    )
    due_soon = with_effective_deadline(recommendations).filter(
        current_deadline__gte=today,
        current_deadline__lte=today + timedelta(days=7),
        status__in=RESPONSE_DUE_STATUSES,
    )

    monthly_cases = list(
        cases.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("pk"))
        .order_by("-month")[:12]
    )
    monthly_cases.reverse()

    reviewed_responses = responses.filter(review__isnull=False).select_related("review")
    review_days = [
        (response.review.reviewed_at - response.submitted_at).total_seconds() / 86400
        for response in reviewed_responses
    ]

    return {
        "total_cases": cases.count(),
        "open_cases": cases.exclude(status=AuditCase.Status.CLOSED).count(),
        "closed_cases": cases.filter(status=AuditCase.Status.CLOSED).count(),
        "organizations_count": cases.values("audited_organization_id").distinct().count(),
        "total_findings": findings.count(),
        "critical_findings": findings.filter(
            risk_level=Finding.RiskLevel.CRITICAL
        ).count(),
        "high_risk_findings": findings.filter(
            risk_level__in=[Finding.RiskLevel.HIGH, Finding.RiskLevel.CRITICAL]
        ).count(),
        "total_recommendations": recommendations.count(),
        "pending_reviews": responses.filter(review__isnull=True).count(),
        "overdue_recommendations": overdue.count(),
        "due_soon_recommendations": due_soon.count(),
        "terminal_recommendations": terminal_count,
        "complied_recommendations": complied_count,
        "compliance_rate": percentage(complied_count, terminal_count),
        "resolution_rate": percentage(terminal_count, recommendations.count()),
        "average_review_days": (
            round(sum(review_days) / len(review_days), 1) if review_days else None
        ),
        "case_status_distribution": distribution(
            cases, "status", AuditCase.Status.choices
        ),
        "recommendation_status_distribution": distribution(
            recommendations, "status", Recommendation.Status.choices
        ),
        "risk_distribution": distribution(
            findings, "risk_level", Finding.RiskLevel.choices
        ),
        "monthly_cases": monthly_cases,
        "monthly_cases_max": max(
            (row["count"] for row in monthly_cases), default=1
        ),
    }
