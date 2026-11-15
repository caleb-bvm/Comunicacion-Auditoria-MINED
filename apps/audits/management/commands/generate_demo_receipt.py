from io import BytesIO
import hashlib

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from reportlab.pdfgen import canvas

from apps.accounts.models import User

from ...models import Evidence, Recommendation, Response
from ...pdf import build_response_receipt


class Command(BaseCommand):
    help = "Genera una constancia de ejemplo para revisión visual local."

    def handle(self, *args, **options):
        try:
            recommendation = Recommendation.objects.get(
                finding__case__reference="IA/NA-010-2025", number=1
            )
            user = User.objects.get(username="centro.10754")
        except (Recommendation.DoesNotExist, User.DoesNotExist) as exc:
            raise CommandError("Ejecute primero manage.py seed_demo.") from exc

        response, _ = Response.objects.get_or_create(
            recommendation=recommendation,
            version=1,
            defaults={
                "declared_status": Response.DeclaredStatus.COMPLETED,
                "action_description": (
                    "El Consejo Directivo Escolar aprobó el procedimiento actualizado para registrar "
                    "los otros ingresos. Se actualizaron el libro de ingresos y el libro de bancos, y "
                    "se estableció una revisión mensual de los documentos de respaldo."
                ),
                "responsible_name": "Responsable Institucional",
                "responsible_job_title": "Dirección del centro educativo",
                "accuracy_declaration": True,
                "submitted_by": user,
            },
        )
        if not response.evidence.exists():
            source = BytesIO()
            source_pdf = canvas.Canvas(source)
            source_pdf.drawString(72, 760, "Acta de demostración para revisión local")
            source_pdf.save()
            source.seek(0)
            evidence = Evidence(
                response=response,
                original_filename="acta-cde-demostracion.pdf",
                category=Evidence.Category.MINUTES,
                description="Acta que documenta la aprobación del nuevo procedimiento.",
                size=len(source.getvalue()),
                sha256=hashlib.sha256(source.getvalue()).hexdigest(),
                scan_status=Evidence.ScanStatus.CLEAN,
                uploaded_by=user,
            )
            evidence.file.save("acta-cde-demostracion.pdf", ContentFile(source.getvalue()), save=False)
            evidence.save()

        for evidence in response.evidence.all():
            digest = hashlib.sha256()
            with evidence.file.open("rb") as source_file:
                for chunk in iter(lambda: source_file.read(8192), b""):
                    digest.update(chunk)
            evidence.sha256 = digest.hexdigest()
            evidence.save(update_fields=["sha256"])

        pdf_buffer, _ = build_response_receipt(response)
        output_dir = settings.BASE_DIR / "output" / "pdf"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "constancia-respuesta-demostracion.pdf"
        output_path.write_bytes(pdf_buffer.getvalue())
        self.stdout.write(self.style.SUCCESS(str(output_path)))
