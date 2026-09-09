import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from apps.accounts.models import User
from apps.audits.models import ActivityLog
from .models import Organization


class EmailDirectoryImportTests(TestCase):
    def source(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "cuentas.xlsx"
        workbook = Workbook()
        workbook.active.append(["Nº", "Codigo de Centro Escolar", "Nombre de Centro Escolar", "Email Address"])
        for index, row in enumerate(rows, 1):
            workbook.active.append([index, *row])
        workbook.save(path)
        workbook.close()
        return path

    def test_merge_preserves_history_geography_passwords_and_account_status(self):
        center = Organization.objects.create(code="00123", name="Nombre oficial existente",
            kind="educational_center", district="Distrito existente", is_active=False)
        account = User.objects.create_user(username="centro.00123", organization=center,
            role="institution", is_active=False, password="ClaveAnterior!2026")
        password = account.password
        source = self.source([
            ("00123", "Nombre del archivo", "00123@example.edu.sv"),
            ("00999", "Centro nuevo", "00999@example.edu.sv"),
        ])
        call_command("import_center_emails", str(source), stdout=StringIO())
        center.refresh_from_db()
        account.refresh_from_db()
        self.assertEqual(center.name, "Nombre oficial existente")
        self.assertEqual(center.district, "Distrito existente")
        self.assertFalse(center.is_active)
        self.assertEqual(center.email, "00123@example.edu.sv")
        self.assertEqual(account.email, center.email)
        self.assertEqual(account.username, "00123")
        self.assertEqual(account.password, password)
        self.assertFalse(account.is_active)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Organization.objects.count(), 2)
        output = StringIO()
        call_command("import_center_emails", str(source), stdout=output)
        self.assertIn("sin_cambios=2", output.getvalue())
        self.assertEqual(ActivityLog.objects.filter(action="center_email_directory_imported").count(), 1)

    def test_dry_run_has_no_writes(self):
        path = self.source([("00123", "Centro", "00123@example.edu.sv")])
        call_command("import_center_emails", str(path), dry_run=True, stdout=StringIO())
        self.assertFalse(Organization.objects.exists())
        self.assertFalse(User.objects.exists())
        self.assertFalse(ActivityLog.objects.exists())

    def test_duplicate_invalid_missing_or_formula_values_fail_atomically(self):
        cases = [
            [("00123", "Centro", "uno@example.edu.sv"), ("00123", "Duplicado", "dos@example.edu.sv")],
            [("00123", "Centro", "uno@example.edu.sv"), ("00999", "Otro", "UNO@example.edu.sv")],
            [("00123", "Centro", "correo-invalido")],
            [("00123", "Centro", "")],
            [(123, "Centro", "uno@example.edu.sv")],
            [("00123", "=1+1", "uno@example.edu.sv")],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(CommandError):
                call_command("import_center_emails", str(self.source(rows)), stdout=StringIO())
            self.assertFalse(Organization.objects.exists())

    def test_existing_email_conflict_rejects_entire_import(self):
        Organization.objects.create(code="other", name="Otro", kind="educational_center", email="uno@example.edu.sv")
        path = self.source([("00123", "Centro", "uno@example.edu.sv")])
        with self.assertRaises(CommandError):
            call_command("import_center_emails", str(path), stdout=StringIO())
        self.assertEqual(Organization.objects.count(), 1)

    def test_custom_test_accounts_keep_their_username_and_receive_email(self):
        center = Organization.objects.create(code="00123", name="Centro", kind="educational_center")
        account = User.objects.create_user(username="cuenta.de.prueba", role="institution", organization=center)
        path = self.source([("00123", "Centro", "uno@example.edu.sv")])
        call_command("import_center_emails", str(path), stdout=StringIO())
        account.refresh_from_db()
        self.assertEqual(account.username, "cuenta.de.prueba")
        self.assertEqual(account.email, "uno@example.edu.sv")
