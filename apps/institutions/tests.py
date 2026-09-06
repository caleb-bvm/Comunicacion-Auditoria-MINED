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
            "code,name,kind,educational_center_type,department,municipality,district,address,is_active\n"
            "CE-100,Centro Escolar Central,educational_center,Centro escolar,Sonsonate,Sonsonate,"
            "Distrito 01-01,Calle Central 10,true\n"
        )
        call_command("import_organizations", str(source), stdout=StringIO())
        center = Organization.objects.get(code="CE-100")
        self.assertEqual(center.name, "Centro Escolar Central")
        self.assertEqual(center.educational_center_type, "Centro escolar")
        self.assertEqual(center.district, "Distrito 01-01")
        self.assertEqual(center.address, "Calle Central 10")
        self.assertTrue(center.is_active)

        source.write_text(
            "code,name,kind,educational_center_type,department,municipality,district,address,is_active\n"
            "CE-100,Centro Escolar Actualizado,educational_center,Complejo educativo,Sonsonate,Izalco,"
            "Distrito 03-02,Avenida Principal 25,true\n",
            encoding="utf-8",
        )
        call_command("import_organizations", str(source), stdout=StringIO())
        center.refresh_from_db()
        self.assertEqual(center.name, "Centro Escolar Actualizado")
        self.assertEqual(center.educational_center_type, "Complejo educativo")
        self.assertEqual(center.municipality, "Izalco")
        self.assertEqual(center.district, "Distrito 03-02")
        self.assertEqual(center.address, "Avenida Principal 25")

    def test_import_keeps_district_optional_for_existing_csv_files(self):
        existing = Organization.objects.create(
            code="CE-150",
            name="Nombre anterior",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            educational_center_type="Instituto técnico",
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
        self.assertEqual(existing.educational_center_type, "Instituto técnico")
        self.assertEqual(existing.district, "Distrito ya registrado")
        self.assertEqual(new_center.district, "")

    def test_dry_run_validates_without_saving(self):
        source = self.make_csv("code,name\nCE-200,Centro de simulación\n")
        output = StringIO()
        call_command("import_organizations", str(source), dry_run=True, stdout=output)
        self.assertFalse(Organization.objects.filter(code="CE-200").exists())
        self.assertIn("SIMULACIÓN completada", output.getvalue())


class OrganizationDisplayTests(TestCase):
    def test_display_address_does_not_repeat_components_already_in_address(self):
        center = Organization(
            code="CE-300",
            name="Centro de prueba",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            department="San Salvador",
            municipality="San Salvador Sur",
            district="Distrito de San Marcos",
            address="Distrito de San Marcos, San Salvador Sur, San Salvador",
        )

        self.assertEqual(
            center.display_address,
            "Distrito de San Marcos, San Salvador Sur, San Salvador",
        )

    def test_display_address_completes_partial_or_missing_catalog_addresses(self):
        partial = Organization(
            code="CE-301",
            name="Centro parcial",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            department="Sonsonate",
            municipality="Izalco",
            district="Distrito Norte",
            address="Calle Principal 12",
        )
        missing = Organization(
            code="CE-302",
            name="Centro sin ubicación",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )

        self.assertEqual(
            partial.display_address,
            "Calle Principal 12, Distrito Norte, Izalco, Sonsonate",
        )
        self.assertEqual(missing.display_address, "Dirección no registrada")

    def test_display_center_type_accepts_catalog_values_and_supports_legacy_records(self):
        imported = Organization(
            code="CE-303",
            name="Centro especializado",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            educational_center_type="Centro de educación especial",
        )
        legacy = Organization(
            code="CE-304",
            name="Complejo Educativo de prueba",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )

        self.assertEqual(imported.display_center_type, "Centro de educación especial")
        self.assertEqual(legacy.display_center_type, "Complejo educativo")
