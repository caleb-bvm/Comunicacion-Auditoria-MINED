"""Import previous PDF reports from unordered folders, matching each file by the code in its name."""
import csv
import re
from collections import Counter
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.audits.historical_documents import save_historical_bundle
from apps.audits.models import ActivityLog, AuditDocument
from apps.audits.services import file_sha256
from apps.core.validators import validate_evidence_file
from apps.institutions.models import Organization

TOKEN = re.compile(r"[A-Z0-9]+")
DIGITS = re.compile(r"\d+")
# Hyphenated codes (DDE-SANTA-ANA) may appear with spaces or underscores in file names.
MAX_CODE_PARTS = 4
REPORT_COLUMNS = ["ruta", "estado", "codigo", "institucion", "detalle", "documento_id"]


def detect_codes(stem, codes):
    """Return the known codes written in a file name, ignoring codes nested in a longer match."""
    tokens = TOKEN.findall(stem.upper())
    matches = []
    for size in range(MAX_CODE_PARTS, 0, -1):
        for start in range(len(tokens) - size + 1):
            candidate = "-".join(tokens[start:start + size])
            end = start + size
            if candidate in codes and not any(s <= start and end <= e for s, e, _ in matches):
                matches.append((start, end, candidate))
    found = {candidate for _, _, candidate in matches}
    if not found:
        # Fallback for names such as "CE10234_informe.pdf", where the code is glued to text.
        found = {run for run in DIGITS.findall(stem) if run in codes}
    return found


class Command(BaseCommand):
    help = ("Importa informes anteriores en PDF desde una carpeta (con subcarpetas), "
            "asignando cada archivo por el código institucional de su nombre.")

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--user", required=True, help="Usuario de Auditoría responsable de la carga.")
        parser.add_argument("--visibility", choices=AuditDocument.Visibility.values,
                            default=AuditDocument.Visibility.AUDIT_ONLY)
        parser.add_argument("--report", help="Ruta del reporte CSV. Por defecto se crea en la carpeta actual.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        root = Path(options["folder"]).resolve()
        if not root.is_dir():
            raise CommandError("No se encontró la carpeta indicada.")
        user = User.objects.filter(username=options["user"], is_active=True).first()
        if user is None or not user.is_audit_staff:
            raise CommandError("El usuario debe existir, estar activo y pertenecer a Auditoría.")
        report_path = Path(options["report"] or f"importacion_informes_{timezone.localtime():%Y%m%d_%H%M%S}.csv")
        dry_run = options["dry_run"]

        organizations = {}
        for organization in Organization.objects.only("pk", "code", "name"):
            organizations.setdefault(organization.code.strip().upper(), []).append(organization)
        files = sorted(path for path in root.rglob("*")
                       if path.suffix.lower() == ".pdf" and path.is_file() and not path.is_symlink())
        if not files:
            raise CommandError("La carpeta no contiene archivos PDF.")

        registered = set(AuditDocument.objects.filter(
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT, parent_report__isnull=True,
        ).values_list("organization_id", "sha256"))
        rows, counts = [], Counter()
        for path in files:
            row = self.process(path, organizations, registered, user, options["visibility"], dry_run)
            row["ruta"] = str(path.relative_to(root))
            counts[row["estado"]] += 1
            rows.append(row)

        with report_path.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.DictWriter(output, fieldnames=REPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        if not dry_run and counts["importado"]:
            ActivityLog.objects.create(
                actor=user, action="historical_reports_imported", target_type="AuditDocument",
                details={"folder": root.name, "files": len(files), **counts},
            )
        mode = "SIMULACIÓN" if dry_run else "IMPORTACIÓN"
        self.stdout.write(f"{mode}: {len(files)} PDF. " + "; ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        self.stdout.write(f"Reporte: {report_path.resolve()}")

    def process(self, path, organizations, registered, user, visibility, dry_run):
        codes = detect_codes(path.stem, organizations)
        candidates = [item for code in codes for item in organizations[code]]
        if not candidates:
            return {"estado": "sin_codigo", "detalle": "El nombre no contiene un código institucional registrado."}
        if len(candidates) > 1:
            return {"estado": "varios_codigos", "codigo": ", ".join(sorted(item.code for item in candidates)),
                    "detalle": "El nombre contiene más de un código; renombre el archivo y repita la importación."}
        organization = candidates[0]
        row = {"codigo": organization.code, "institucion": organization.name}
        try:
            with path.open("rb") as handle:
                uploaded = File(handle, name=path.name)
                digest = file_sha256(uploaded)
                if (organization.pk, digest) in registered:
                    return {**row, "estado": "ya_registrado",
                            "detalle": "El mismo archivo ya existe para esta institución o se repite en la carpeta."}
                if dry_run:
                    validate_evidence_file(uploaded)
                    document = None
                else:
                    document = save_historical_bundle(user=user, attachments=[], report_data={
                        "organization": organization, "file": uploaded, "title": path.stem[:300],
                        "reference": "", "document_date": None, "visibility": visibility,
                    })
        except ValidationError as exc:
            return {**row, "estado": "error", "detalle": " ".join(exc.messages)}
        except OSError:
            return {**row, "estado": "error", "detalle": "No se pudo leer o guardar el archivo; puede reintentarlo."}
        # Copies of one PDF in several folders are imported once per institution.
        registered.add((organization.pk, digest))
        return {**row, "estado": "listo" if dry_run else "importado", "documento_id": document.pk if document else ""}
