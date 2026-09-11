import os
import tempfile
from datetime import date
from pathlib import Path
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.scanning import protected_file_response, scan_file
from apps.core.validators import validate_evidence_file


@override_settings(FILE_SCAN_REQUIRED=True)
class AntivirusTests(SimpleTestCase):
    def socket(self, response):
        connection = MagicMock()
        connection.recv.return_value = response
        context = MagicMock()
        context.__enter__.return_value = connection
        return context, connection

    def test_clean_file_protocol_and_position(self):
        context, connection = self.socket(b"stream: OK\0")
        file = BytesIO(b"%PDF-example")
        file.seek(3)
        with patch("apps.core.scanning.socket.create_connection", return_value=context):
            scan_file(file)
        self.assertEqual(file.tell(), 3)
        self.assertEqual(connection.sendall.call_args_list[0].args[0], b"zINSTREAM\0")
        self.assertEqual(connection.sendall.call_args_list[-1].args[0], b"\0\0\0\0")

    def test_infected_and_inconclusive_files_are_never_served(self):
        for reply in (b"stream: test FOUND\0", b"stream: ERROR\0", b"stream: OK", b""):
            with self.subTest(reply=reply):
                context, _ = self.socket(reply)
                file = BytesIO(b"%PDF-example")
                with patch("apps.core.scanning.socket.create_connection", return_value=context):
                    response = protected_file_response(file, as_attachment=True, filename="test.pdf")
                self.assertEqual(response.status_code, 503)
                self.assertTrue(file.closed)
                self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_unavailable_scanner_rejects_upload(self):
        file = SimpleUploadedFile("test.pdf", b"%PDF-example")
        with patch("apps.core.scanning.socket.create_connection", side_effect=TimeoutError):
            with self.assertRaises(ValidationError):
                validate_evidence_file(file)
        self.assertEqual(file.tell(), 0)

    def test_upload_rejects_infected_file_with_valid_header(self):
        context, _ = self.socket(b"stream: test FOUND\0")
        with patch("apps.core.scanning.socket.create_connection", return_value=context):
            with self.assertRaises(ValidationError):
                validate_evidence_file(SimpleUploadedFile("test.pdf", b"%PDF-example"))

    def test_clean_upload_is_accepted(self):
        context, _ = self.socket(b"stream: OK\0")
        with patch("apps.core.scanning.socket.create_connection", return_value=context):
            validate_evidence_file(SimpleUploadedFile("test.pdf", b"%PDF-example"))


@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
class LoginProtectionTests(TestCase):
    def setUp(self):
        self.password = "PruebaSeguraDeAcceso!2026"
        self.user = User.objects.create_user(
            username="audit-security", password=self.password,
            role=User.Role.AUDITOR, must_change_password=False,
        )

    def post_login(self, password, username="audit-security", **extra):
        return self.client.post(reverse("login"), {"username": username, "password": password}, **extra)

    def test_lockout_blocks_correct_password_and_changed_ip(self):
        for _ in range(3):
            response = self.post_login("incorrecta")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "900")
        self.assertEqual(self.post_login(self.password, REMOTE_ADDR="192.0.2.2").status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_resets_failed_attempts(self):
        self.post_login("incorrecta")
        self.post_login("incorrecta")
        self.assertEqual(self.post_login(self.password).status_code, 302)
        self.client.logout()
        self.assertEqual(self.post_login("incorrecta").status_code, 200)

    def test_admin_login_also_locks(self):
        for _ in range(3):
            response = self.client.post("/administracion/login/", {
                "username": self.user.username, "password": "incorrecta",
            })
        self.assertEqual(response.status_code, 429)

    def test_other_accounts_on_shared_network_are_not_locked(self):
        for _ in range(3):
            self.post_login("incorrecta")
        User.objects.create_user(username="another", password=self.password, must_change_password=False)
        self.assertEqual(self.post_login(self.password, username="another").status_code, 302)

    def test_absolute_session_expiry_and_private_cache(self):
        self.post_login(self.password)
        self.assertEqual(self.client.get(reverse("account_profile"))["Cache-Control"], "private, no-store")
        session = self.client.session
        session["authenticated_at"] = 1
        session.save()
        response = self.client.get(reverse("account_profile"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class ProductionSettingsTests(SimpleTestCase):
    environment = {
        "DJANGO_SECRET_KEY": "test-only-9c4f82e71a356b048d21fbe5a901673c52ea804b9d6f",
        "DJANGO_ALLOWED_HOSTS": "auditoria.example.org",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://auditoria.example.org",
        "PUBLIC_BASE_URL": "https://auditoria.example.org",
        "POSTGRES_DB": "test", "POSTGRES_USER": "test", "POSTGRES_PASSWORD": "test",
        "POSTGRES_HOST": "db.example.org", "EMAIL_HOST": "smtp.example.org",
        "DEFAULT_FROM_EMAIL": "auditoria@example.org", "FILE_SCAN_REQUIRED": "true",
        "PRIVATE_MEDIA_ROOT": str(Path("tmp/security-private").resolve()),
    }

    def load_settings(self, **changes):
        # Un proceso separado evita modificar settings.base de la aplicación de pruebas.
        import subprocess
        import sys
        env = {**os.environ, **self.environment, **changes}
        return subprocess.run(
            [sys.executable, "-c", "import config.settings.production"],
            env=env, capture_output=True, text=True,
        )

    def test_secure_settings_load(self):
        result = self.load_settings()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsafe_settings_fail_closed(self):
        for changes in (
            {"FILE_SCAN_REQUIRED": "false"},
            {"DJANGO_ALLOWED_HOSTS": "*"},
            {"PUBLIC_BASE_URL": "http://auditoria.example.org"},
            {"POSTGRES_SSLMODE": "prefer"},
            {"EMAIL_USE_TLS": "false", "EMAIL_USE_SSL": "false"},
            {"DJANGO_SECRET_KEY": "x" * 60},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.load_settings(**changes).returncode, 0)


@override_settings(FILE_SCAN_REQUIRED=True)
class PrivateDownloadTests(TestCase):
    def setUp(self):
        from apps.audits.models import AuditDocument
        from apps.institutions.models import Organization, SchoolBoardPeriod

        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        media = override_settings(MEDIA_ROOT=storage.name)
        media.enable()
        self.addCleanup(media.disable)
        center = Organization.objects.create(code="SEC1", name="Centro", kind="educational_center")
        other = Organization.objects.create(code="SEC2", name="Otro", kind="educational_center")
        self.owner = User.objects.create_user(username="owner", organization=center, must_change_password=False)
        self.stranger = User.objects.create_user(username="stranger", organization=other, must_change_password=False)
        # Simula documentos heredados, guardados antes de integrar el antivirus.
        document = AuditDocument.objects.create(
            organization=center, document_type="historical_report", status="historical",
            visibility="institution", title="Anterior", original_filename="test.pdf",
            file=SimpleUploadedFile("test.pdf", b"%PDF-legacy"),
        )
        period = SchoolBoardPeriod.objects.create(
            organization=center, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            school_year_start=2026, school_year_end=2026,
            supporting_document=SimpleUploadedFile("acta.pdf", b"%PDF-legacy"),
            created_by=self.owner, updated_by=self.owner,
        )
        self.urls = [reverse("download_audit_document", args=[document.pk]),
                     reverse("cde_period_document", args=[period.pk])]

    def test_legacy_downloads_fail_closed(self):
        from apps.audits.models import ActivityLog
        self.client.force_login(self.owner)
        for url in self.urls:
            with self.subTest(url=url), patch(
                "apps.core.scanning.scan_file", side_effect=ValidationError("Sin verificar")
            ) as scanner:
                self.assertEqual(self.client.get(url).status_code, 503)
                scanner.assert_called_once()
        self.assertFalse(ActivityLog.objects.filter(action="audit_document_downloaded").exists())

    def test_unauthorized_downloads_do_not_reach_scanner(self):
        self.client.force_login(self.stranger)
        for url in self.urls:
            with self.subTest(url=url), patch("apps.core.scanning.scan_file") as scanner:
                self.assertIn(self.client.get(url).status_code, (403, 404))
                scanner.assert_not_called()

    def test_clean_authorized_downloads_keep_content_and_no_store(self):
        self.client.force_login(self.owner)
        for url in self.urls:
            with self.subTest(url=url), patch("apps.core.scanning.scan_file"):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"%PDF-legacy")
                self.assertEqual(response["Cache-Control"], "private, no-store")
                response.close()
