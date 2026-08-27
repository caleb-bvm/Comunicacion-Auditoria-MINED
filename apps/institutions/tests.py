import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from .models import Organization


class ImportOrganizationsCommandTests(TestCase):
    def make_csv(self, content):
        temporary = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        temporary.close()
        path = Path(temporary.name)
        path.write_text(content, encoding="utf-8")
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_import_creates_and_updates_organizations_by_code(self):
        source = self.make_csv(
            "code,name,kind,department,municipality,district,is_active\n"
            "CE-100,Centro Escolar Central,educational_center,Sonsonate,Sonsonate,"
            "Distrito 01-01,true\n"
        )
        call_command("import_organizations", str(source), stdout=StringIO())
        center = Organization.objects.get(code="CE-100")
        self.assertEqual(center.name, "Centro Escolar Central")
        self.assertEqual(center.district, "Distrito 01-01")
        self.assertTrue(center.is_active)

        source.write_text(
            "code,name,kind,department,municipality,district,is_active\n"
            "CE-100,Centro Escolar Actualizado,educational_center,Sonsonate,Izalco,"
            "Distrito 03-02,true\n",
            encoding="utf-8",
        )
        call_command("import_organizations", str(source), stdout=StringIO())
        center.refresh_from_db()
        self.assertEqual(center.name, "Centro Escolar Actualizado")
        self.assertEqual(center.municipality, "Izalco")
        self.assertEqual(center.district, "Distrito 03-02")

    def test_import_keeps_district_optional_for_existing_csv_files(self):
        existing = Organization.objects.create(
            code="CE-150",
            name="Nombre anterior",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            district="Distrito ya registrado",
        )
        source = self.make_csv(
            "code,name,kind,department,municipality,is_active\n"
            "CE-150,Centro actualizado,educational_center,Sonsonate,Izalco,true\n"
            "CE-151,Centro sin distrito,educational_center,Sonsonate,Izalco,true\n"
        )

        call_command("import_organizations", str(source), stdout=StringIO())

        existing.refresh_from_db()
        new_center = Organization.objects.get(code="CE-151")
        self.assertEqual(existing.name, "Centro actualizado")
        self.assertEqual(existing.district, "Distrito ya registrado")
        self.assertEqual(new_center.district, "")

    def test_dry_run_validates_without_saving(self):
        source = self.make_csv("code,name\nCE-200,Centro de simulación\n")
        output = StringIO()
        call_command("import_organizations", str(source), dry_run=True, stdout=output)
        self.assertFalse(Organization.objects.filter(code="CE-200").exists())
        self.assertIn("SIMULACIÓN completada", output.getvalue())
