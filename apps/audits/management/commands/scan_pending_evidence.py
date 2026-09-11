from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.audits.models import Evidence
from apps.core.scanning import scan_file


class Command(BaseCommand):
    help = "Analiza evidencias pendientes; solo aprueba archivos verificados por ClamAV."

    def handle(self, *args, **options):
        if not settings.FILE_SCAN_REQUIRED:
            raise CommandError("Active el antivirus para ejecutar este comando.")
        approved = 0
        pending = 0
        for evidence in Evidence.objects.filter(scan_status=Evidence.ScanStatus.PENDING).iterator():
            try:
                with evidence.file.open("rb") as file:
                    scan_file(file)
            except (ValidationError, OSError):
                pending += 1
                continue
            Evidence.objects.filter(pk=evidence.pk, scan_status=Evidence.ScanStatus.PENDING).update(
                scan_status=Evidence.ScanStatus.CLEAN
            )
            approved += 1
        self.stdout.write(f"Verificadas: {approved}; pendientes o rechazadas por análisis: {pending}.")
        if pending:
            raise CommandError("Hay archivos sin aprobar. Revise el antivirus y los archivos pendientes.")
