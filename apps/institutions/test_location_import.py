import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from .models import Organization


class CenterLocationImportTests(TestCase):
    headers = [
        "CODIGO CE", "NOMBRE CE", "DEPARTAMENTO", "DISTRITO", "DIRECCION",
        "LATITUD", "LONGITUD",
    ]

    def source(self, rows):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "ubicaciones.xlsx"
        workbook = Workbook()
        workbook.active.append(self.headers)
        for row in rows:
            workbook.active.append(row)
        workbook.save(path)
        workbook.close()
        return path

    def test_imports_exact_and_verified_legacy_code_matches(self):
        exact = Organization.objects.create(
            code="10001", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        legacy = Organization.objects.create(
            code="cod10002", name='Centro Escolar "Dos"',
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        source = self.source([
            [10001, "Nombre distinto que no reemplaza el oficial", "AHUACHAPAN", "AHUACHAPAN",
             "Primera dirección", 13.918585, -89.849243],
            [10002, "CENTRO ESCOLAR DOS", "SANTA ANA", "SANTA ANA",
             "Segunda dirección", 13.990001, -89.550002],
        ])

        output = StringIO()
        call_command("import_center_locations", str(source), stdout=output)
        exact.refresh_from_db()
        legacy.refresh_from_db()

        self.assertEqual(exact.department, "AHUACHAPAN")
        self.assertEqual(exact.district, "AHUACHAPAN")
        self.assertEqual(exact.address, "Primera dirección")
        self.assertEqual(exact.latitude, Decimal("13.9185850"))
        self.assertEqual(exact.longitude, Decimal("-89.8492430"))
        self.assertEqual(exact.name, "Centro Uno")
        self.assertEqual(legacy.latitude, Decimal("13.9900010"))
        self.assertIn("alias_cod=1", output.getvalue())

    def test_dry_run_does_not_write_and_missing_coordinates_preserve_existing_values(self):
        center = Organization.objects.create(
            code="10001", name="Centro", kind=Organization.Kind.EDUCATIONAL_CENTER,
            latitude=Decimal("13.5000000"), longitude=Decimal("-89.5000000"),
        )
        source = self.source([
            [10001, "Centro", "LA LIBERTAD", "COLÓN", "Dirección nueva", None, None],
        ])
        call_command("import_center_locations", str(source), dry_run=True, stdout=StringIO())
        center.refresh_from_db()
        self.assertEqual(center.department, "")
        self.assertEqual(center.latitude, Decimal("13.5000000"))

        call_command("import_center_locations", str(source), stdout=StringIO())
        center.refresh_from_db()
        self.assertEqual(center.department, "LA LIBERTAD")
        self.assertEqual(center.address, "Dirección nueva")
        self.assertEqual(center.latitude, Decimal("13.5000000"))

    def test_unmatched_rows_do_not_create_organizations(self):
        source = self.source([
            [99999, "Centro inexistente", "MORAZÁN", "JOCOAITIQUE", "Dirección", 13.7, -88.1],
        ])
        output = StringIO()
        call_command("import_center_locations", str(source), stdout=output)
        self.assertFalse(Organization.objects.exists())
        self.assertIn("no_encontradas=1", output.getvalue())

    def test_rejects_duplicate_formula_partial_or_out_of_country_coordinates(self):
        cases = [
            [[10001, "Centro", "A", "B", "C", 13.5, -89.5],
             [10001, "Centro repetido", "A", "B", "C", 13.6, -89.6]],
            [[10001, "Centro", "A", "B", "C", "=1+1", -89.5]],
            [[10001, "Centro", "A", "B", "C", 13.5, None]],
            [[10001, "Centro", "A", "B", "C", 20, -89.5]],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(CommandError):
                call_command("import_center_locations", str(self.source(rows)), stdout=StringIO())
            self.assertFalse(Organization.objects.exists())
