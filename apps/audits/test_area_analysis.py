from datetime import date, datetime, timedelta
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import AuditCase, Finding, FindingCategory, Recommendation
from .territorial_analysis import build_territorial_analysis

TODAY = date(2026, 11, 18)


class AreaAnalysisTests(TestCase):
    """Hallazgos por área auditada en el análisis de Dirección y su exportación."""

    def setUp(self):
        audit_unit = Organization.objects.create(
            code="DAI-AREA", name="Dirección de Auditoría", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.center = Organization.objects.create(
            code="CE-AREA", name="Centro Escolar Área", kind=Organization.Kind.EDUCATIONAL_CENTER,
            department="Departamento A", municipality="Municipio A", district="Distrito A1",
        )
        self.director = User.objects.create_user(
            username="directora-areas", role=User.Role.AUDIT_MANAGER, organization=audit_unit,
            must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor-areas", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.finance = FindingCategory.objects.create(name="Gestión financiera")
        self.inventory = FindingCategory.objects.create(name="Inventario")
        self.empty_area = FindingCategory.objects.create(name="Infraestructura")
        self.retired = FindingCategory.objects.create(name="Área retirada", is_active=False)
        self.retired_unused = FindingCategory.objects.create(name="Retirada sin datos", is_active=False)
        self.sequence = 0

    def finding(self, category, *, risk=Finding.RiskLevel.MEDIUM, statuses=(), case_status=AuditCase.Status.PUBLISHED,
                created=None, deadline=None):
        self.sequence += 1
        case = AuditCase.objects.create(
            reference=f"AREA-{self.sequence}", title="Expediente", audited_organization=self.center,
            assigned_auditor=self.auditor, created_by=self.auditor, status=case_status,
        )
        if created:
            AuditCase.objects.filter(pk=case.pk).update(
                created_at=timezone.make_aware(datetime.combine(created, datetime.min.time()))
            )
        finding = Finding.objects.create(
            case=case, number=1, title="Hallazgo", risk_level=risk, category=category
        )
        for number, status in enumerate(statuses, start=1):
            Recommendation.objects.create(
                finding=finding, number=number, text="Atender.", responsible_organization=self.center,
                status=status, deadline=deadline,
            )
        return finding

    def rows_by_name(self, analysis):
        return {row["name"]: row for row in analysis["area_rows"]}

    def test_current_snapshot_counts_findings_and_compliance_by_area(self):
        complied, partial, not_complied, pending = (
            Recommendation.Status.COMPLIED, Recommendation.Status.PARTIAL,
            Recommendation.Status.NOT_COMPLIED, Recommendation.Status.PENDING,
        )
        self.finding(self.finance, risk=Finding.RiskLevel.CRITICAL, statuses=(complied, complied, not_complied))
        self.finding(self.finance, risk=Finding.RiskLevel.LOW, statuses=(partial,))
        self.finding(self.inventory, risk=Finding.RiskLevel.HIGH, statuses=(pending,))
        self.finding(self.retired, statuses=(complied,))
        self.finding(None, statuses=(pending,))
        # Los borradores no cuentan.
        self.finding(self.finance, statuses=(complied,), case_status=AuditCase.Status.DRAFT)

        analysis = build_territorial_analysis({"mode": "current"}, today=TODAY)
        rows = self.rows_by_name(analysis)
        finance = rows["Gestión financiera"]
        self.assertEqual(finance["finding_count"], 2)
        self.assertEqual(finance["high_risk_count"], 1)
        self.assertEqual(finance["recommendation_count"], 4)
        self.assertEqual(finance["terminal_count"], 4)
        self.assertEqual(finance["complied_count"], 2)
        self.assertEqual(finance["compliance_rate"], 50)
        self.assertEqual(finance["finding_share"], 40)
        # Sin resultados definitivos el cumplimiento es N/D, no 0 %.
        self.assertIsNone(rows["Inventario"]["compliance_rate"])
        self.assertEqual(rows["Infraestructura"]["finding_count"], 0)
        self.assertFalse(rows["Área retirada"]["is_active"])
        self.assertNotIn("Retirada sin datos", rows)
        self.assertEqual(analysis["area_rows"][-1]["name"], "Sin área")
        self.assertEqual(analysis["area_rows"][0]["name"], "Gestión financiera")
        totals = analysis["area_totals"]
        self.assertEqual(totals["finding_count"], 5)
        # Cumplimiento total con totales (3 de 5), no promedio de porcentajes por área.
        self.assertEqual((totals["complied_count"], totals["terminal_count"]), (3, 5))
        self.assertEqual(totals["compliance_rate"], 60)
        self.assertEqual(analysis["area_scope_label"], "Todo el historial consolidado")

    def test_overdue_uses_the_effective_deadline(self):
        self.finding(self.finance, statuses=(Recommendation.Status.PENDING,), deadline=TODAY - timedelta(days=2))
        self.finding(self.finance, statuses=(Recommendation.Status.PENDING,), deadline=TODAY + timedelta(days=2))
        analysis = build_territorial_analysis({"mode": "current"}, today=TODAY)
        self.assertEqual(self.rows_by_name(analysis)["Gestión financiera"]["overdue_count"], 1)
        self.assertEqual(analysis["area_totals"]["overdue_count"], 1)

    def test_activity_mode_uses_only_cases_from_the_period(self):
        self.finding(self.finance, created=date(2026, 3, 1))
        self.finding(self.finance, created=date(2025, 3, 1))
        current = build_territorial_analysis({"mode": "current"}, today=TODAY)
        activity = build_territorial_analysis({"mode": "activity", "period": "year"}, today=TODAY)
        self.assertEqual(self.rows_by_name(current)["Gestión financiera"]["finding_count"], 2)
        self.assertEqual(self.rows_by_name(activity)["Gestión financiera"]["finding_count"], 1)
        self.assertEqual(activity["area_scope_label"], "Año actual")

    def test_page_shows_the_area_table_in_both_modes(self):
        self.finding(self.inventory, statuses=(Recommendation.Status.PENDING,))
        self.client.force_login(self.director)
        for mode in ("current", "activity"):
            with self.subTest(mode=mode):
                page = self.client.get(reverse("director_statistics"), {"mode": mode})
                self.assertContains(page, "Hallazgos por área auditada")
                self.assertContains(page, "Inventario")
                self.assertContains(page, "N/D")

    def test_deep_export_matches_the_page(self):
        self.finding(self.finance, statuses=(Recommendation.Status.COMPLIED, Recommendation.Status.NOT_COMPLIED))
        self.finding(self.inventory, statuses=(Recommendation.Status.PENDING,))
        self.client.force_login(self.director)
        params = {"mode": "current", "depth": "deep"}
        page = self.client.get(reverse("director_statistics"), params)
        response = self.client.get(reverse("director_statistics_xlsx"), params)
        workbook = load_workbook(BytesIO(b"".join(response.streaming_content)))
        sheet = workbook["Áreas auditadas"]
        exported = {
            sheet.cell(row, 1).value: [sheet.cell(row, column).value for column in range(2, 10)]
            for row in range(5, sheet.max_row + 1)
            if sheet.cell(row, 1).value
        }
        for row in page.context["area_rows"]:
            expected_rate = row["compliance_rate"] / 100 if row["compliance_rate"] is not None else "N/D"
            self.assertEqual(
                exported[row["name"]],
                [row["finding_count"], row["finding_share"] / 100, row["high_risk_count"],
                 row["recommendation_count"], row["overdue_count"], row["terminal_count"],
                 row["complied_count"], expected_rate],
            )
        self.assertEqual(exported["Total"][0], page.context["area_totals"]["finding_count"])
        controls = workbook["Calidad y metodología"]
        control_row = next(
            row for row in controls.iter_rows(min_row=5, values_only=True)
            if row[1] == "Áreas auditadas exportadas"
        )
        self.assertEqual(control_row[4], "OK")

        light_response = self.client.get(reverse("director_statistics_xlsx"), {"mode": "current", "depth": "light"})
        light = load_workbook(BytesIO(b"".join(light_response.streaming_content)))
        self.assertNotIn("Áreas auditadas", light.sheetnames)
