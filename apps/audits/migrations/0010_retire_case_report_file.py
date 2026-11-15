import hashlib

from django.core.files.storage import default_storage
from django.db import migrations
from django.db.models import Max


def _file_metadata(name):
    """Tamaño y huella del archivo; 0 y vacío si no está en el almacenamiento."""
    try:
        digest = hashlib.sha256()
        size = 0
        with default_storage.open(name, "rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return size, digest.hexdigest()
    except OSError:
        return 0, ""


def preserve_legacy_reports(apps, schema_editor):
    """Registra como documento cada informe PDF heredado que aún no tenga uno.

    El documento apunta al mismo archivo (no se copia ni se elimina nada), así que
    sigue verificado por verify_private_storage después de quitar el campo.
    """
    AuditCase = apps.get_model("audits", "AuditCase")
    AuditDocument = apps.get_model("audits", "AuditDocument")
    private_statuses = {"draft", "pending_publication"}
    for case in AuditCase.objects.exclude(report_file="").iterator():
        name = case.report_file.name
        if AuditDocument.objects.filter(file=name).exists():
            continue
        size, sha256 = _file_metadata(name)
        common = {
            "case_id": case.pk,
            "organization_id": case.audited_organization_id,
            "reference": case.reference,
            "document_date": case.report_date,
            "file": name,
            "original_filename": f"{case.reference}.pdf",
            "size": size,
            "sha256": sha256,
            "uploaded_by_id": case.created_by_id,
        }
        latest = AuditDocument.objects.filter(case_id=case.pk, document_type="report").aggregate(
            latest=Max("version")
        )["latest"]
        if latest is None:
            # Sin informe registrado: el PDF heredado pasa a ser la versión 1.
            if case.status == "draft":
                status = "draft"
            elif case.status == "pending_publication":
                status = "pending_approval"
            else:
                status = "approved"
            AuditDocument.objects.create(
                document_type="report",
                title=case.title[:300],
                version=1,
                status=status,
                visibility="audit_only" if case.status in private_statuses else "institution",
                **common,
            )
        else:
            # Ya hay versiones del informe: el PDF se conserva solo para Auditoría,
            # sin desplazar a la versión vigente.
            other_version = (
                AuditDocument.objects.filter(case_id=case.pk, document_type="other").aggregate(
                    latest=Max("version")
                )["latest"]
                or 0
            ) + 1
            AuditDocument.objects.create(
                document_type="other",
                title="Informe heredado en PDF",
                version=other_version,
                status="historical",
                visibility="audit_only",
                **common,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("audits", "0009_auditinquiry_auditinquirymessage_and_more"),
    ]

    operations = [
        migrations.RunPython(preserve_legacy_reports, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="auditcase",
            name="report_file",
        ),
    ]
