import csv
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.institutions.models import Organization
from .management.commands.import_historical_reports import detect_codes
from .models import ActivityLog, AuditDocument


class HistoricalImportTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        override = override_settings(MEDIA_ROOT=storage.name)
        override.enable()
        self.addCleanup(override.disable)
        source = tempfile.TemporaryDirectory()
        self.addCleanup(source.cleanup)
        self.root = Path(source.name)
        self.report = self.root / "reporte.csv"
        self.center = Organization.objects.create(code="10234", name="Centro Escolar Uno", kind="educational_center")
        self.other = Organization.objects.create(code="10235", name="Centro Escolar Dos", kind="educational_center")
        # Created by the institutions data migration; TransactionTestCase flushes may have removed them.
        self.office, _ = Organization.objects.get_or_create(code="DDE-CUSCATLAN", defaults={
            "name": "Departamental", "kind": "departmental_office"})
        self.audit_unit, _ = Organization.objects.get_or_create(code="DAI-MINED", defaults={
            "name": "Auditoría Interna", "kind": "ministry_unit"})
        self.auditor = User.objects.create_user(username="auditor.import", role="auditor", must_change_password=False)
        self.institution = User.objects.create_user(username="10234", role="institution", organization=self.center)

    def pdf(self, relative, content="informe"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"%PDF-1.4\n{content}".encode())
        return path

    def run_import(self, *extra, user="auditor.import"):
        out = StringIO()
        call_command("import_historical_reports", str(self.root), "--user", user,
                     "--report", str(self.report), *extra, stdout=out)
        with self.report.open(encoding="utf-8-sig") as handle:
            return {row["ruta"].replace("\\", "/"): row for row in csv.DictReader(handle)}, out.getvalue()

    def test_detects_codes_by_whole_token_hyphenated_and_glued_digits(self):
        codes = {"10234": [], "10235": [], "DDE-SANTA-ANA": [], "SANTA": [], "DDE-CUSCATLAN": []}
        self.assertEqual(detect_codes("Informe 2019_10234 final", codes), {"10234"})
        self.assertEqual(detect_codes("CE10234-auditoria", codes), {"10234"})
        self.assertEqual(detect_codes("dde santa ana 2018", codes), {"DDE-SANTA-ANA"})
        self.assertEqual(detect_codes("10234 y 10235", codes), {"10234", "10235"})
        self.assertEqual(detect_codes("Gestión DDE Cuscatlán", codes), {"DDE-CUSCATLAN"})
        self.assertEqual(detect_codes("102345 informe", codes), set())

    def test_imports_unordered_folders_and_reports_files_to_review(self):
        self.pdf("2019/varios/Informe 10234.pdf", "uno")
        self.pdf("otra carpeta/IA_dde-cuscatlán_2018.PDF", "dos")
        self.pdf("sin orden/informe general.pdf", "tres")
        self.pdf("sin orden/10234 y 10235.pdf", "cuatro")
        self.pdf("copia/Informe 10234 (copia).pdf", "uno")
        (self.root / "notas.txt").write_text("no es pdf")
        (self.root / "falso 10235.pdf").write_bytes(b"no es un pdf")
        rows, output = self.run_import()

        self.assertEqual(rows["2019/varios/Informe 10234.pdf"]["estado"], "importado")
        self.assertEqual(rows["otra carpeta/IA_dde-cuscatlán_2018.PDF"]["codigo"], "DDE-CUSCATLAN")
        self.assertEqual(rows["sin orden/informe general.pdf"]["codigo"], "DAI-MINED")
        self.assertEqual(rows["sin orden/informe general.pdf"]["por_defecto"], "sí")
        self.assertEqual(rows["sin orden/10234 y 10235.pdf"]["estado"], "varios_codigos")
        self.assertEqual(rows["copia/Informe 10234 (copia).pdf"]["estado"], "ya_registrado")
        self.assertEqual(rows["falso 10235.pdf"]["estado"], "error")
        self.assertEqual(len(rows), 6)
        self.assertIn("importado=3", output)
        self.assertIn("por_defecto=1", output)

        report = AuditDocument.objects.get(organization=self.center)
        self.assertEqual(report.document_type, AuditDocument.DocumentType.HISTORICAL_REPORT)
        self.assertEqual(report.status, AuditDocument.Status.HISTORICAL)
        self.assertEqual(report.visibility, AuditDocument.Visibility.AUDIT_ONLY)
        self.assertIsNone(report.case)
        self.assertEqual(report.uploaded_by, self.auditor)
        self.assertEqual((report.title, report.original_filename), ("Informe 10234", "Informe 10234.pdf"))
        self.assertTrue(Path(report.file.path).is_file())
        self.assertEqual(AuditDocument.objects.filter(organization=self.office).count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action="historical_document_uploaded").count(), 3)
        self.assertEqual(ActivityLog.objects.get(action="historical_reports_imported").details["importado"], 3)

    def test_rerun_is_idempotent(self):
        self.pdf("Informe 10234.pdf", "uno")
        self.pdf("informe general.pdf", "dos")
        self.run_import()
        rows, _ = self.run_import()
        self.assertEqual(rows["Informe 10234.pdf"]["estado"], "ya_registrado")
        self.assertEqual(rows["informe general.pdf"]["estado"], "ya_registrado")
        self.assertEqual(AuditDocument.objects.count(), 2)

    def test_files_without_a_registered_institution_go_to_the_default_institution(self):
        self.pdf("Gestión DNES 2020.pdf", "unidad")
        self.pdf("CE Cton Veracruz CI 11978.pdf", "no registrado")
        self.pdf("CE CI 11978 (10234).pdf", "dudoso")
        self.pdf("Informe 10235.pdf", "centro")
        rows, _ = self.run_import()
        for name, detail in (("Gestión DNES 2020.pdf", "no contiene"), ("CE Cton Veracruz CI 11978.pdf", "11978")):
            self.assertEqual(rows[name]["estado"], "importado")
            self.assertEqual(rows[name]["codigo"], "DAI-MINED")
            self.assertIn(detail, rows[name]["detalle"])
        self.assertEqual(rows["CE CI 11978 (10234).pdf"]["estado"], "varios_codigos")
        self.assertEqual(rows["Informe 10235.pdf"]["por_defecto"], "")
        self.assertEqual(AuditDocument.objects.filter(organization=self.audit_unit).count(), 2)
        self.pdf("Otra unidad.pdf", "otra")
        rows, _ = self.run_import("--default-code", "DDE-CUSCATLAN")
        self.assertEqual(rows["Otra unidad.pdf"]["codigo"], "DDE-CUSCATLAN")
        with self.assertRaises(CommandError):
            self.run_import("--default-code", "NO-EXISTE")

    def test_dry_run_validates_without_saving(self):
        self.pdf("Informe 10234.pdf")
        rows, output = self.run_import("--dry-run")
        self.assertEqual(rows["Informe 10234.pdf"]["estado"], "listo")
        self.assertIn("SIMULACIÓN", output)
        self.assertFalse(AuditDocument.objects.exists())
        self.assertFalse(ActivityLog.objects.exists())

    def test_visibility_option_and_staff_requirement(self):
        self.pdf("Informe 10234.pdf")
        self.run_import("--visibility", "institution")
        self.assertEqual(AuditDocument.objects.get().visibility, AuditDocument.Visibility.INSTITUTION)
        with self.assertRaises(CommandError):
            self.run_import(user="10234")
        with self.assertRaises(CommandError):
            self.run_import(user="inexistente")
