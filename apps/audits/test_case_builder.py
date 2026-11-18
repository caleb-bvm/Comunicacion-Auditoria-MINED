from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import ActivityLog, AuditCase, BusinessDayHoliday, Finding, Recommendation
from .services import add_business_days, recommendation_deadline_shortcuts


class CaseBuilderAssistanceTests(TestCase):
    """Ayudas del formulario de hallazgos y recomendaciones para el personal auditor."""

    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        self.auditor.assigned_organizations.add(self.center)
        self.other_auditor = User.objects.create_user(
            username="otro-auditor",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        # Viernes 13 de noviembre de 2026.
        self.case = AuditCase.objects.create(
            reference="IA-BUILDER-001",
            title="Fondos de funcionamiento",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
            report_date=date(2026, 11, 13),
            response_deadline=date(2026, 12, 18),
        )
        self.finding = Finding.objects.create(
            case=self.case,
            number=1,
            title="Falta de conciliaciones",
            risk_level=Finding.RiskLevel.HIGH,
            condition="No se elaboraron conciliaciones.",
        )
        self.recommendation = Recommendation.objects.create(
            finding=self.finding,
            number=1,
            text="Elabore las conciliaciones mensuales.",
            responsible_organization=self.center,
            deadline=date(2026, 12, 18),
        )
        self.client.force_login(self.auditor)

    def finding_payload(self, **overrides):
        payload = {
            "number": 2,
            "title": "Inventario desactualizado",
            "risk_level": Finding.RiskLevel.MEDIUM,
            "condition": "El inventario no incluye las compras de 2026.",
            "criteria": "El instructivo exige actualizar el inventario.",
            "cause": "No se asignó un responsable.",
            "effect": "Bienes sin control.",
        }
        payload.update(overrides)
        return payload

    def recommendation_payload(self, **overrides):
        payload = {
            "number": 2,
            "text": "Designe al responsable del inventario.",
            "responsible_organization": self.center.pk,
            "deadline": "2026-12-18",
            "evidence_requirements": "Acta de designación.",
        }
        payload.update(overrides)
        return payload

    def test_finding_form_shows_guiding_questions_and_examples(self):
        page = self.client.get(reverse("finding_create", args=[self.case.pk]))
        self.assertContains(page, "¿Qué se encontró?")
        self.assertContains(page, "¿Qué norma, disposición o procedimiento")
        self.assertContains(page, "Ver ejemplo", count=5)
        self.assertContains(page, "Guardar y agregar recomendación")

    def test_save_finding_and_continue_with_its_first_recommendation(self):
        result = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            self.finding_payload(next="recommendation"),
        )
        finding = self.case.findings.get(number=2)
        self.assertRedirects(result, reverse("recommendation_create", args=[finding.pk]))

    def test_save_finding_only_returns_to_the_finding_in_the_builder(self):
        result = self.client.post(
            reverse("finding_create", args=[self.case.pk]),
            self.finding_payload(next=""),
        )
        finding = self.case.findings.get(number=2)
        self.assertRedirects(
            result, reverse("case_builder", args=[self.case.pk]) + f"#hallazgo-{finding.pk}"
        )

    def test_save_recommendation_and_add_another(self):
        result = self.client.post(
            reverse("recommendation_create", args=[self.finding.pk]),
            self.recommendation_payload(next="another"),
        )
        self.assertRedirects(result, reverse("recommendation_create", args=[self.finding.pk]))
        self.assertTrue(self.finding.recommendations.filter(number=2).exists())

    def test_recommendation_form_shows_finding_context_and_deadline_shortcuts(self):
        page = self.client.get(reverse("recommendation_create", args=[self.finding.pk]))
        self.assertContains(page, "Falta de conciliaciones")
        self.assertContains(page, "10 días hábiles")
        self.assertContains(page, 'data-value="2026-11-27"')
        self.assertContains(page, "Fecha general")
        self.assertContains(page, 'data-value="2026-12-18"')

    def test_deadline_shortcuts_skip_weekends_and_active_holidays(self):
        BusinessDayHoliday.objects.create(date=date(2026, 11, 16), name="Asueto de prueba")
        BusinessDayHoliday.objects.create(
            date=date(2026, 11, 17), name="Asueto inactivo", is_active=False
        )
        shortcuts = recommendation_deadline_shortcuts(self.case, (10, 30))
        self.assertEqual(shortcuts[0], {"label": "10 días hábiles", "value": date(2026, 11, 30)})
        self.assertEqual(shortcuts[1]["value"], add_business_days(date(2026, 11, 13), 30))
        self.assertEqual(shortcuts[-1], {"label": "Fecha general", "value": date(2026, 12, 18)})

    def test_deadline_shortcuts_count_from_today_without_report_date(self):
        self.case.report_date = None
        self.case.response_deadline = None
        shortcuts = recommendation_deadline_shortcuts(self.case, (10,), today=date(2026, 11, 18))
        self.assertEqual(shortcuts, [{"label": "10 días hábiles", "value": date(2026, 12, 2)}])

    def test_publication_requires_the_four_attributes_and_evidence(self):
        page = self.client.get(reverse("case_publish", args=[self.case.pk]))
        self.assertContains(page, "Complete el criterio, la causa y el efecto del hallazgo 1.")
        self.assertContains(page, "Complete las evidencias requeridas de la recomendación 1.1.")

        Finding.objects.filter(pk=self.finding.pk).update(
            criteria="Criterio.", cause="Causa.", effect="   "
        )
        page = self.client.get(reverse("case_publish", args=[self.case.pk]))
        self.assertContains(page, "Complete el efecto del hallazgo 1.")

    def test_builder_flags_incomplete_findings_and_recommendations(self):
        page = self.client.get(reverse("case_builder", args=[self.case.pk]))
        self.assertContains(page, "Falta redactar")
        self.assertContains(page, "Falta completar las evidencias requeridas")
        self.assertContains(page, f'id="hallazgo-{self.finding.pk}"')

    def test_duplicate_recommendation_creates_next_number_and_opens_it(self):
        self.recommendation.evidence_requirements = "Conciliaciones firmadas."
        self.recommendation.save()
        result = self.client.post(reverse("recommendation_duplicate", args=[self.recommendation.pk]))
        copy = self.finding.recommendations.get(number=2)
        self.assertRedirects(result, reverse("recommendation_edit", args=[copy.pk]))
        self.assertEqual(copy.text, self.recommendation.text)
        self.assertEqual(copy.responsible_organization, self.center)
        self.assertEqual(copy.deadline, self.recommendation.deadline)
        self.assertEqual(copy.evidence_requirements, "Conciliaciones firmadas.")
        self.assertIsNone(copy.source_recommendation)
        self.assertTrue(
            ActivityLog.objects.filter(
                case=self.case, action="recommendation_duplicated"
            ).exists()
        )

    def test_duplicate_requires_post_and_edit_permission(self):
        url = reverse("recommendation_duplicate", args=[self.recommendation.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

        self.client.force_login(self.other_auditor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.finding.recommendations.count(), 1)

    def test_published_case_cannot_be_duplicated_into(self):
        self.case.status = AuditCase.Status.PUBLISHED
        self.case.save(update_fields=["status"])
        result = self.client.post(
            reverse("recommendation_duplicate", args=[self.recommendation.pk])
        )
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.finding.recommendations.count(), 1)

    def test_edit_form_keeps_existing_dates_in_native_date_inputs(self):
        # <input type="date"> solo acepta AAAA-MM-DD; con el formato regional el campo
        # se mostraba vacío y la fecha se perdía al guardar.
        page = self.client.get(reverse("recommendation_edit", args=[self.recommendation.pk]))
        self.assertContains(page, 'type="date" name="deadline" value="2026-12-18"', html=False)
        page = self.client.get(reverse("case_edit", args=[self.case.pk]))
        self.assertContains(page, 'name="report_date" value="2026-11-13"', html=False)
