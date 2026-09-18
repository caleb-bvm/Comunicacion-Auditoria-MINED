import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import F, Max, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    BusinessDayHoliday,
    DeadlineExtension,
    Finding,
    Recommendation,
)


def file_sha256(uploaded_file):
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def next_document_version(case, document_type):
    latest = case.documents.filter(document_type=document_type).aggregate(
        value=Max("version")
    )["value"]
    return (latest or 0) + 1


def create_audit_document(*, uploaded_file, user, **values):
    return AuditDocument.objects.create(
        file=uploaded_file,
        original_filename=uploaded_file.name[:255],
        size=uploaded_file.size,
        sha256=file_sha256(uploaded_file),
        uploaded_by=user,
        **values,
    )


def add_business_days(start_date, business_days):
    if business_days < 1:
        raise ValueError("La cantidad de días hábiles debe ser mayor que cero.")

    current = start_date
    added = 0
    while added < business_days:
        current += timedelta(days=1)
        is_weekday = current.weekday() < 5
        is_holiday = BusinessDayHoliday.objects.filter(
            date=current,
            is_active=True,
        ).exists()
        if is_weekday and not is_holiday:
            added += 1
    return current


def with_effective_deadline(queryset=None):
    """Annotate recommendations with the latest granted deadline, when present."""
    queryset = queryset if queryset is not None else Recommendation.objects.all()
    latest_extension_deadline = (
        DeadlineExtension.objects.filter(recommendation_id=OuterRef("pk"))
        .order_by("-granted_at", "-pk")
        .values("new_deadline")[:1]
    )
    return queryset.annotate(
        current_deadline=Coalesce(
            Subquery(latest_extension_deadline),
            F("deadline"),
        )
    )


@transaction.atomic
def copy_historical_recommendations(case, historical_recommendations):
    source_ids = [item.pk for item in historical_recommendations]
    already_imported = set(
        Recommendation.objects.filter(
            finding__case=case,
            source_recommendation_id__in=source_ids,
        ).values_list("source_recommendation_id", flat=True)
    )
    pending_sources = [item for item in historical_recommendations if item.pk not in already_imported]
    if not pending_sources:
        return []

    finding = case.findings.filter(
        title="Seguimiento a recomendaciones de auditorías anteriores"
    ).first()
    if finding is None:
        next_finding_number = (case.findings.aggregate(value=Max("number"))["value"] or 0) + 1
        finding = Finding.objects.create(
            case=case,
            number=next_finding_number,
            title="Seguimiento a recomendaciones de auditorías anteriores",
            risk_level=Finding.RiskLevel.HIGH,
            condition=(
                "Recomendaciones emitidas en informes anteriores que requieren un nuevo "
                "seguimiento de su cumplimiento."
            ),
        )

    next_number = (finding.recommendations.aggregate(value=Max("number"))["value"] or 0) + 1
    created = []
    for source in pending_sources:
        recommendation = Recommendation.objects.create(
            finding=finding,
            number=next_number,
            text=source.text,
            responsible_organization=(
                source.responsible_organization or case.audited_organization
            ),
            deadline=case.response_deadline,
            evidence_requirements=(
                "Adjunte el documento que respalde las acciones realizadas para atender "
                "esta recomendación."
            ),
            source_recommendation=source,
        )
        created.append(recommendation)
        next_number += 1
    return created


@transaction.atomic
def mark_overdue_recommendations(today=None):
    today = today or timezone.localdate()
    overdue = list(
        with_effective_deadline(
            Recommendation.objects.select_for_update(of=("self",)).select_related("finding__case")
        )
        .filter(
            current_deadline__lt=today,
            no_response_recorded_at__isnull=True,
            finding__case__status__in=[
                AuditCase.Status.PUBLISHED,
                AuditCase.Status.IN_RESPONSE,
                AuditCase.Status.UNDER_REVIEW,
                AuditCase.Status.CORRECTION_REQUIRED,
            ],
            status__in=[
                Recommendation.Status.PENDING,
                Recommendation.Status.CORRECTION_REQUIRED,
            ],
        )
    )
    recorded_at = timezone.now()
    for recommendation in overdue:
        previous_status = recommendation.status
        recommendation.status = Recommendation.Status.NOT_COMPLIED
        recommendation.no_response_recorded_at = recorded_at
        recommendation.save(update_fields=["status", "no_response_recorded_at"])
        ActivityLog.objects.create(
            actor=None,
            case=recommendation.finding.case,
            action="recommendation_no_response",
            target_type="Recommendation",
            target_id=str(recommendation.pk),
            details={
                "previous_status": previous_status,
                "new_status": Recommendation.Status.NOT_COMPLIED,
                "deadline": recommendation.current_deadline.isoformat(),
                "reason": "No se recibió una respuesta dentro del plazo vigente.",
            },
        )
    return len(overdue)
