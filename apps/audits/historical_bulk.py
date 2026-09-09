"""Reviewable, one-file-at-a-time historical imports for audit staff."""
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.institutions.models import Organization
from .forms import HistoricalAttachmentForm
from .historical_documents import save_historical_bundle
from .models import AuditDocument
from .services import file_sha256


class BulkHistoricalFileForm(HistoricalAttachmentForm):
    parent_report = forms.ModelChoiceField(queryset=AuditDocument.objects.none(), required=False)

    def __init__(self, *args, center, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_type"].choices = [
            ("historical_report", "Informe anterior"),
            *self.fields["document_type"].choices,
        ]
        self.fields["parent_report"].queryset = reports_for(center)

    def clean(self):
        cleaned = super().clean()
        is_report = cleaned.get("document_type") == "historical_report"
        if is_report:
            if cleaned.get("parent_report"):
                self.add_error("parent_report", "Un informe anterior no puede depender de otro informe.")
            uploaded = cleaned.get("file")
            if uploaded and Path(uploaded.name).suffix.lower() not in {".pdf", ".docx"}:
                self.add_error("file", "El informe debe ser PDF o Word (.docx).")
        elif not cleaned.get("parent_report"):
            self.add_error("parent_report", "Seleccione un informe de este centro para el documento.")
        return cleaned


def reports_for(center):
    return AuditDocument.objects.filter(
        organization=center, document_type="historical_report",
        parent_report__isnull=True, case__isnull=True, status="historical",
    )


def check_staff(user):
    if not user.is_audit_staff:
        raise PermissionDenied("Esta acción corresponde al personal de Auditoría.")


@login_required
@require_GET
def historical_bulk_upload(request, organization_pk=None):
    check_staff(request.user)
    center = None
    centers = []
    query = request.GET.get("q", "").strip()[:150]
    if organization_pk is not None:
        center = get_object_or_404(Organization, pk=organization_pk, kind="educational_center")
    elif query:
        centers = Organization.objects.filter(kind="educational_center").filter(
            Q(code__icontains=query) | Q(name__icontains=query)
        ).order_by("code")[:40]
    config = None
    if center:
        form = BulkHistoricalFileForm(center=center)
        reports = [{"id": item.pk, "title": item.title, "reference": item.reference,
                    "visibility": item.visibility} for item in reports_for(center).order_by("-document_date", "-pk")]
        selected = request.GET.get("report", "")
        config = {
            "url": reverse("historical_bulk_file", args=[center.pk]),
            "reports": reports,
            "selectedReport": selected if any(str(r["id"]) == selected for r in reports) else "",
            "types": list(form.fields["document_type"].choices),
            "visibilities": list(AuditDocument.Visibility.choices),
            "maxMB": settings.FILE_MAX_UPLOAD_MB, "maxFiles": 100,
        }
    return render(request, "audits/historical_bulk_upload.html", {
        "center": center, "centers": centers, "query": query,
        "bulk_config": config, "max_file_mb": settings.FILE_MAX_UPLOAD_MB,
    })


@login_required
@require_POST
def historical_bulk_file(request, organization_pk):
    check_staff(request.user)
    center = get_object_or_404(Organization, pk=organization_pk, kind="educational_center")
    form = BulkHistoricalFileForm(request.POST, request.FILES, center=center)
    if len(request.FILES.getlist("file")) != 1 or len(request.FILES) != 1:
        return JsonResponse({"error": "Envíe un archivo por solicitud."}, status=400)
    if not form.is_valid():
        return JsonResponse({"error": " ".join(str(e) for errors in form.errors.values() for e in errors)}, status=400)
    data = form.cleaned_data
    parent = data.pop("parent_report", None)
    digest = file_sha256(data["file"])
    try:
        # The same center lock used by individual uploads serializes duplicate checks.
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=center.pk)
            candidates = reports_for(center) if parent is None else AuditDocument.objects.filter(
                organization=center).filter(Q(pk=parent.pk) | Q(parent_report=parent))
            existing = candidates.filter(sha256=digest).first()
            duplicate = existing is not None
            if existing:
                report = parent or existing
                document = existing
            elif parent:
                report = save_historical_bundle(user=request.user, report_id=parent.pk, attachments=[data])
                document = report.attachments.get(sha256=digest)
            else:
                report = save_historical_bundle(user=request.user, report_data={**data, "organization": center}, attachments=[])
                document = report
        return JsonResponse({
            "status": "duplicate" if duplicate else "saved", "document_id": document.pk,
            "report_id": report.pk, "url": reverse("historical_document_detail", args=[report.pk]),
            "message": "Duplicado: se conserva el documento existente y sus datos." if duplicate else "Guardado",
        })
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    except OSError:
        return JsonResponse({"error": "No se pudo guardar el archivo. Puede reintentarlo."}, status=503)
