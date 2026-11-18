import hashlib
import re
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
    FindingTemplate,
    Recommendation,
    RecommendationTemplate,
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


def add_business_days(start_date, business_days, holidays=None):
    """Suma días hábiles excluyendo fines de semana y asuetos activos.

    `holidays` permite pasar un conjunto de fechas ya consultado para evitar
    una consulta por cada día recorrido."""
    if business_days < 1:
        raise ValueError("La cantidad de días hábiles debe ser mayor que cero.")

    current = start_date
    added = 0
    while added < business_days:
        current += timedelta(days=1)
        is_weekday = current.weekday() < 5
        if holidays is None:
            is_holiday = BusinessDayHoliday.objects.filter(
                date=current,
                is_active=True,
            ).exists()
        else:
            is_holiday = current in holidays
        if is_weekday and not is_holiday:
            added += 1
    return current


def recommendation_deadline_shortcuts(case, business_day_counts, today=None, suggested_days=None):
    """Fechas sugeridas para la fecha límite de una recomendación.

    Se cuentan desde la fecha del informe (o desde hoy si aún no se ha indicado) e
    incluyen la fecha límite general del expediente cuando existe."""
    start = case.report_date or today or timezone.localdate()
    counts = sorted(set(business_day_counts))
    shortcuts = []
    if counts:
        # Margen amplio: cada semana tiene cinco días hábiles y los asuetos son pocos.
        horizon = start + timedelta(days=counts[-1] * 2 + 30)
        holidays = set(
            BusinessDayHoliday.objects.filter(
                is_active=True, date__gt=start, date__lte=horizon
            ).values_list("date", flat=True)
        )
        shortcuts = [
            {
                "label": f"{count} días hábiles{' (sugerido)' if count == suggested_days else ''}",
                "value": add_business_days(start, count, holidays),
            }
            for count in counts
        ]
    if case.response_deadline:
        shortcuts.append({"label": "Fecha general", "value": case.response_deadline})
    return shortcuts


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
            criteria=(
                "Las recomendaciones emitidas por la Dirección de Auditoría Interna deben "
                "atenderse y documentarse dentro del plazo establecido."
            ),
            cause=(
                "Las acciones informadas no permitieron dar por cumplidas las recomendaciones "
                "en el seguimiento anterior."
            ),
            effect=(
                "Persisten las condiciones que originaron las recomendaciones y el riesgo "
                "asociado a ellas."
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


# Datos por completar que Dirección deja en las plantillas, por ejemplo "[período revisado]".
PLACEHOLDER_PATTERN = re.compile(r"\[[^\[\]\n]{1,80}\]")
FINDING_TEXT_FIELDS = ("title", "condition", "criteria", "cause", "effect")


def has_placeholders(*texts):
    return any(PLACEHOLDER_PATTERN.search(text or "") for text in texts)


def _holidays_between(start, end):
    return set(
        BusinessDayHoliday.objects.filter(
            is_active=True, date__gt=start, date__lte=end
        ).values_list("date", flat=True)
    )


@transaction.atomic
def create_finding_from_template(case, template, today=None):
    """Copia una plantilla de la biblioteca al expediente como un hallazgo nuevo.

    La copia es independiente: editar o desactivar la plantilla después no cambia el
    hallazgo. Los plazos se cuentan desde la fecha del informe (o desde hoy)."""
    case = type(case).objects.select_for_update().get(pk=case.pk)
    next_number = (case.findings.aggregate(value=Max("number"))["value"] or 0) + 1
    finding = Finding.objects.create(
        case=case,
        number=next_number,
        category=template.category,
        source_template=template,
        risk_level=template.risk_level,
        **{name: getattr(template, name) for name in FINDING_TEXT_FIELDS},
    )
    items = list(template.recommendations.order_by("number"))
    start = case.report_date or today or timezone.localdate()
    longest = max((item.business_days or 0 for item in items), default=0)
    holidays = _holidays_between(start, start + timedelta(days=longest * 2 + 30)) if longest else set()
    for number, item in enumerate(items, start=1):
        deadline = (
            add_business_days(start, item.business_days, holidays)
            if item.business_days
            else case.response_deadline
        )
        Recommendation.objects.create(
            finding=finding,
            number=number,
            text=item.text,
            responsible_organization=case.audited_organization,
            deadline=deadline,
            evidence_requirements=item.evidence_requirements,
        )
    return finding


@transaction.atomic
def create_template_from_finding(finding, user):
    """Guarda un hallazgo real como plantilla inactiva para que Dirección la depure."""
    template = FindingTemplate.objects.create(
        category=finding.category,
        risk_level=finding.risk_level,
        is_active=False,
        created_by=user,
        **{name: getattr(finding, name) for name in FINDING_TEXT_FIELDS},
    )
    for number, recommendation in enumerate(finding.recommendations.order_by("number"), start=1):
        RecommendationTemplate.objects.create(
            finding_template=template,
            number=number,
            text=recommendation.text,
            evidence_requirements=recommendation.evidence_requirements,
        )
    return template


@transaction.atomic
def create_finding_from_finding(case, source):
    """Copia un hallazgo de otro expediente del mismo auditor como punto de partida.

    El centro auditado del expediente actual queda como responsable y las fechas límite
    toman la fecha general; el texto debe adaptarse porque describe otro caso."""
    case = type(case).objects.select_for_update().get(pk=case.pk)
    next_number = (case.findings.aggregate(value=Max("number"))["value"] or 0) + 1
    finding = Finding.objects.create(
        case=case,
        number=next_number,
        category=source.category,
        risk_level=source.risk_level,
        **{name: getattr(source, name) for name in FINDING_TEXT_FIELDS},
    )
    for number, recommendation in enumerate(source.recommendations.order_by("number"), start=1):
        Recommendation.objects.create(
            finding=finding,
            number=number,
            text=recommendation.text,
            responsible_organization=case.audited_organization,
            deadline=case.response_deadline,
            evidence_requirements=recommendation.evidence_requirements,
        )
    return finding
