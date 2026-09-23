"""Comprueba las dependencias externas antes de habilitar producción."""
import socket
import tempfile

from django.conf import settings
from django.core.mail import get_connection
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Verifica base de datos, migraciones, almacenamiento, ClamAV y SMTP de producción."

    def handle(self, *args, **options):
        if settings.DEBUG:
            raise CommandError("La verificación debe ejecutarse con la configuración de producción.")
        if not settings.FILE_SCAN_REQUIRED:
            raise CommandError("El análisis antivirus debe estar activo.")

        checks = (
            ("Base de datos", self.check_database),
            ("Migraciones", self.check_migrations),
            ("Almacenamiento privado", self.check_private_storage),
            ("Antivirus", self.check_antivirus),
            ("Correo SMTP", self.check_email),
        )
        failures = []
        for label, check in checks:
            try:
                check()
            except Exception as exc:  # cada dependencia debe informar su propio fallo
                failures.append(f"{label}: {exc}")
                self.stderr.write(self.style.ERROR(f"[FALLO] {label}: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"[OK] {label}"))

        if failures:
            raise CommandError(f"La verificación previa encontró {len(failures)} fallo(s).")
        self.stdout.write(self.style.SUCCESS("Entorno de producción listo para iniciar el servicio."))

    @staticmethod
    def check_database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("la consulta de comprobación no respondió correctamente")

    @staticmethod
    def check_migrations():
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        if executor.migration_plan(targets):
            raise RuntimeError("hay migraciones pendientes")

    @staticmethod
    def check_private_storage():
        media_root = settings.MEDIA_ROOT
        if not media_root.is_dir():
            raise RuntimeError(f"no existe el directorio {media_root}")
        with tempfile.NamedTemporaryFile(prefix=".preflight-", dir=media_root):
            pass

    @staticmethod
    def check_antivirus():
        with socket.create_connection(
            (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=settings.CLAMAV_TIMEOUT
        ) as scanner:
            scanner.settimeout(settings.CLAMAV_TIMEOUT)
            scanner.sendall(b"zPING\0")
            if scanner.recv(16) != b"PONG\0":
                raise RuntimeError("ClamAV no respondió PONG")

    @staticmethod
    def check_email():
        email = get_connection(fail_silently=False)
        try:
            if email.open() is False:
                raise RuntimeError("el servidor SMTP no aceptó la conexión")
        finally:
            email.close()
