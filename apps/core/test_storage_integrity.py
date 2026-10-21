import hashlib
import tempfile
from io import StringIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.audits.models import AuditDocument
from apps.institutions.models import Organization


class VerifyPrivateStorageTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        media = override_settings(MEDIA_ROOT=storage.name)
        media.enable()
        self.addCleanup(media.disable)
        self.root = Path(storage.name)
        center = Organization.objects.create(code="00123", name="Centro", kind="educational_center")
        content = b"%PDF-1.4\ninforme"
        self.document = AuditDocument(
            organization=center, document_type="historical_report", title="Informe",
            status="historical", original_filename="informe.pdf", size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        self.document.file.save("informe.pdf", ContentFile(content))
        self.path = Path(self.document.file.path)

    def run_command(self, *args):
        output, errors = StringIO(), StringIO()
        call_command("verify_private_storage", *args, stdout=output, stderr=errors)
        return output.getvalue()

    def assert_fails(self, message, *args):
        errors = StringIO()
        with self.assertRaises(CommandError):
            call_command("verify_private_storage", *args, stdout=StringIO(), stderr=errors)
        self.assertIn(message, errors.getvalue())

    def test_intact_storage_passes_with_checksums(self):
        output = self.run_command("--checksums")
        self.assertIn("Archivos registrados revisados: 1.", output)
        self.assertIn("Almacenamiento privado íntegro.", output)

    def test_missing_file_fails(self):
        self.path.unlink()
        self.assert_fails(f"audits.AuditDocument #{self.document.pk} (file): falta el archivo")

    def test_size_change_fails_without_checksums(self):
        self.path.write_bytes(b"%PDF-1.4\ninforme truncado o alterado")
        self.assert_fails("el tamaño de")

    def test_same_size_alteration_is_detected_only_with_checksums(self):
        self.path.write_bytes(b"%PDF-1.4\nINFORME")
        self.run_command()
        self.assert_fails("la huella SHA-256", "--checksums")

    def test_unregistered_files_are_reported_but_kept(self):
        orphan = self.root / "documentos" / "huerfano.pdf"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"%PDF-1.4\nsin registro")
        (self.root / ".preflight-temporal").write_bytes(b"")
        output = self.run_command()
        self.assertIn("Archivos sin registro en la base de datos: 1.", output)
        self.assertIn("documentos/huerfano.pdf", output)
        self.assertTrue(orphan.exists())

    def test_legacy_rows_without_digest_are_counted(self):
        AuditDocument.objects.filter(pk=self.document.pk).update(sha256="", size=0)
        output = self.run_command("--checksums")
        self.assertIn("sin huella registrada (solo se comprobó su tamaño): 1.", output)
