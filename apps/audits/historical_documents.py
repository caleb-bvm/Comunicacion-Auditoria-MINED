"""Archive original documents without changing the operational audit workflow."""
import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.core.validators import validate_evidence_file
from apps.institutions.models import Organization
from .models import ActivityLog, AuditDocument
from .services import file_sha256


def save_historical_bundle(*, user, attachments, report_data=None, report_id=None):
    if not user.is_authenticated or not user.is_audit_staff:
        raise PermissionDenied("Esta acción corresponde al personal de Auditoría.")
    written_files = []

    def store_file(values, parent=None):
        uploaded = values["file"]
        document = AuditDocument(
            organization=center, parent_report=parent, case=None,
            document_type=values["document_type"], reference=values.get("reference", ""),
            title=values.get("title") or uploaded.name,
            document_date=values.get("document_date"), version=1,
            status=AuditDocument.Status.HISTORICAL, visibility=values["visibility"],
            original_filename=uploaded.name[:255], size=uploaded.size,
            sha256=values["sha256"], uploaded_by=user,
        )
        document.full_clean(exclude=["file"])
        document.file.save(uploaded.name, uploaded, save=False)
        written_files.append((document.file.storage, document.file.name))
        document.save()
        ActivityLog.objects.create(
            actor=user, action="historical_attachment_uploaded" if parent else "historical_document_uploaded",
            target_type="AuditDocument", target_id=str(document.pk),
            details={"organization_id": center.pk, "parent_report_id": parent.pk if parent else None,
                     "document_date": document.document_date.isoformat() if document.document_date else None,
                     "visibility": document.visibility, "document_type": document.document_type},
        )
        return document

    try:
        with transaction.atomic():
            if report_data is not None:
                center_id = report_data["organization"].pk
            else:
                center_id = AuditDocument.objects.get(
                    pk=report_id, document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
                    parent_report__isnull=True, case__isnull=True,
                ).organization_id
            center = Organization.objects.select_for_update().get(pk=center_id)
            prepared = []
            for values in ([report_data] if report_data is not None else []) + attachments:
                validate_evidence_file(values["file"])
                prepared.append({**values, "sha256": file_sha256(values["file"])})
            if report_data is not None:
                report_values = prepared.pop(0)
                if AuditDocument.objects.filter(
                    organization=center, document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
                    parent_report__isnull=True, sha256=report_values["sha256"],
                ).exists():
                    raise ValidationError("Este informe ya está registrado en el centro. Abra el informe existente para agregar documentos.")
                seen = {report_values["sha256"]}
                report = None
            else:
                report = AuditDocument.objects.select_for_update().get(pk=report_id)
                seen = {report.sha256, *report.attachments.values_list("sha256", flat=True)}
            for values in prepared:
                if values["sha256"] in seen:
                    raise ValidationError(f"El archivo «{values['file'].name}» está repetido o ya pertenece a este informe.")
                seen.add(values["sha256"])
            if report is None:
                report = store_file({**report_values, "document_type": AuditDocument.DocumentType.HISTORICAL_REPORT})
            for values in prepared:
                store_file(values, parent=report)
            return report
    except Exception:
        # Only delete new files created by this failed operation, never previous originals.
        for storage, name in written_files:
            try:
                storage.delete(name)
            except OSError:
                logging.getLogger(__name__).warning("No se pudo limpiar un archivo de una carga histórica fallida.")
        raise
