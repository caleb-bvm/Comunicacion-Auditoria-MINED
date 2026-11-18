from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .forms import FindingForm
from .models import (
    ActivityLog,
    AuditCase,
    Finding,
    FindingCategory,
    FindingTemplate,
    Recommendation,
    RecommendationTemplate,
)
from .views import publication_issues


class FindingLibraryTests(TestCase):
    """Biblioteca de hallazgos estándar: Dirección la mantiene y los auditores la usan."""

    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.auditor.assigned_organizations.add(self.center)
        self.other_auditor = User.objects.create_user(
            username="otro-auditor", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="directora", role=User.Role.AUDIT_MANAGER, organization=audit_unit,
            must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="IA-LIB-001",
            title="Fondos de funcionamiento",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
            report_date=date(2026, 11, 13),
            response_deadline=date(2026, 12, 18),
        )
        self.category = FindingCategory.objects.create(name="Gestión financiera")
        self.template = FindingTemplate.objects.create(
            category=self.category,
            title="Falta de conciliaciones bancarias",
            risk_level=Finding.RiskLevel.HIGH,
            condition="Durante [período revisado] no se elaboraron conciliaciones.",
            criteria="El instructivo exige conciliaciones mensuales.",
            cause="Desconocimiento del procedimiento.",
            effect="No se detectan cargos no autorizados.",
            created_by=self.director,
        )
        RecommendationTemplate.objects.create(
            finding_template=self.template, number=1,
            text="Elabore las conciliaciones mensuales.",
            evidence_requirements="Conciliaciones firmadas.", business_days=10,
        )
        RecommendationTemplate.objects.create(
            finding_template=self.template, number=2,
            text="Capacite al tesorero.", evidence_requirements="Constancia de capacitación.",
        )

    def template_payload(self, recommendations, **overrides):
        payload = {
            "category": self.category.pk,
            "title": "Inventario desactualizado",
            "risk_level": Finding.RiskLevel.MEDIUM,
            "condition": "El inventario de [año] no está actualizado.",
            "criteria": "Normas de control interno.",
            "cause": "Sin responsable.",
            "effect": "Riesgo de pérdida de bienes.",
            "is_active": "on",
            "recomendaciones-TOTAL_FORMS": str(len(recommendations)),
            "recomendaciones-INITIAL_FORMS": "0",
            "recomendaciones-MIN_NUM_FORMS": "1",
            "recomendaciones-MAX_NUM_FORMS": "1000",
        }
        for index, item in enumerate(recommendations):
            for key, value in item.items():
                payload[f"recomendaciones-{index}-{key}"] = value
        payload.update(overrides)
        return payload

    # ---------- Dirección ----------

    def test_only_direction_manages_the_library(self):
        for user in (self.auditor, self.other_auditor):
            self.client.force_login(user)
            for url in (
                reverse("director_library"),
                reverse("director_library_category_create"),
                reverse("director_library_template_create"),
                reverse("director_library_template_edit", args=[self.template.pk]),
            ):
                self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.force_login(self.director)
        page = self.client.get(reverse("director_library"))
        self.assertContains(page, "Falta de conciliaciones bancarias")
        self.assertContains(page, reverse("director_library"))

    def test_direction_creates_and_deactivates_a_category(self):
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_library_category_create"),
            {"name": "Inventario", "description": "Bienes muebles", "is_active": "on"},
        )
        self.assertRedirects(result, reverse("director_library"))
        category = FindingCategory.objects.get(name="Inventario")
        self.client.post(
            reverse("director_library_category_edit", args=[category.pk]),
            {"name": "Inventario", "description": "Bienes muebles"},
        )
        category.refresh_from_db()
        self.assertFalse(category.is_active)
        self.assertEqual(
            ActivityLog.objects.filter(action__startswith="library_category_").count(), 2
        )

    def test_direction_creates_a_template_with_numbered_recommendations(self):
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_library_template_create"),
            self.template_payload([
                {"text": "Actualice el inventario.", "evidence_requirements": "Inventario firmado.", "business_days": "15"},
                {"text": "Designe un responsable.", "evidence_requirements": "", "business_days": ""},
            ]),
        )
        self.assertRedirects(result, reverse("director_library"))
        template = FindingTemplate.objects.get(title="Inventario desactualizado")
        self.assertEqual(template.created_by, self.director)
        self.assertEqual(
            list(template.recommendations.values_list("number", "business_days")),
            [(1, 15), (2, None)],
        )
        self.assertTrue(ActivityLog.objects.filter(action="library_template_created").exists())

    def test_template_requires_at_least_one_recommendation(self):
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_library_template_create"),
            self.template_payload([{"text": "", "evidence_requirements": "", "business_days": ""}]),
        )
        self.assertEqual(result.status_code, 200)
        self.assertFalse(FindingTemplate.objects.filter(title="Inventario desactualizado").exists())

    def test_removing_a_recommendation_renumbers_the_rest(self):
        self.client.force_login(self.director)
        first, second = self.template.recommendations.order_by("number")
        payload = self.template_payload(
            [
                {"id": str(first.pk), "finding_template": str(self.template.pk), "text": first.text,
                 "evidence_requirements": first.evidence_requirements, "business_days": "10", "DELETE": "on"},
                {"id": str(second.pk), "finding_template": str(self.template.pk), "text": second.text,
                 "evidence_requirements": second.evidence_requirements, "business_days": ""},
            ],
            title=self.template.title,
            **{"recomendaciones-INITIAL_FORMS": "2"},
        )
        result = self.client.post(
            reverse("director_library_template_edit", args=[self.template.pk]), payload
        )
        self.assertRedirects(result, reverse("director_library"))
        self.assertEqual(
            list(self.template.recommendations.values_list("text", "number")),
            [("Capacite al tesorero.", 1)],
        )

    def test_direction_saves_a_real_finding_as_an_inactive_template(self):
        finding = Finding.objects.create(
            case=self.case, number=1, title="Caja chica sin arqueos",
            risk_level=Finding.RiskLevel.MEDIUM, category=self.category,
            condition="No se realizaron arqueos.", criteria="Norma.", cause="Causa.", effect="Efecto.",
        )
        Recommendation.objects.create(
            finding=finding, number=3, text="Realice arqueos mensuales.",
            responsible_organization=self.center, evidence_requirements="Actas de arqueo.",
        )
        url = reverse("director_library_from_finding", args=[finding.pk])
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.post(url).status_code, 403)

        self.client.force_login(self.director)
        result = self.client.post(url)
        template = FindingTemplate.objects.get(title="Caja chica sin arqueos")
        self.assertRedirects(result, reverse("director_library_template_edit", args=[template.pk]))
        self.assertFalse(template.is_active)
        self.assertEqual(template.category, self.category)
        self.assertEqual(
            list(template.recommendations.values_list("number", "text")),
            [(1, "Realice arqueos mensuales.")],
        )
        case_page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertContains(case_page, "Guardar en biblioteca")

    # ---------- Personal auditor ----------

    def test_auditor_sees_only_active_templates_and_can_filter_by_area(self):
        FindingTemplate.objects.create(
            title="Plantilla retirada", risk_level=Finding.RiskLevel.LOW, is_active=False
        )
        other_category = FindingCategory.objects.create(name="Infraestructura")
        FindingTemplate.objects.create(
            title="Techos en mal estado", risk_level=Finding.RiskLevel.MEDIUM, category=other_category
        )
        self.client.force_login(self.auditor)
        url = reverse("case_library", args=[self.case.pk])
        page = self.client.get(url)
        self.assertContains(page, "Falta de conciliaciones bancarias")
        self.assertContains(page, "Techos en mal estado")
        self.assertNotContains(page, "Plantilla retirada")
        page = self.client.get(url, {"area": other_category.pk})
        self.assertNotContains(page, "Falta de conciliaciones bancarias")
        self.assertContains(page, "Techos en mal estado")
        page = self.client.get(url, {"q": "tesorero"})
        self.assertContains(page, "Falta de conciliaciones bancarias")
        self.assertNotContains(page, "Techos en mal estado")

    def test_using_a_template_copies_the_finding_and_its_recommendations(self):
        Finding.objects.create(
            case=self.case, number=1, title="Previo", risk_level=Finding.RiskLevel.LOW
        )
        self.client.force_login(self.auditor)
        result = self.client.post(
            reverse("case_library_use", args=[self.case.pk, self.template.pk])
        )
        finding = self.case.findings.get(number=2)
        self.assertRedirects(result, reverse("finding_edit", args=[finding.pk]))
        self.assertEqual(finding.source_template, self.template)
        self.assertEqual(finding.category, self.category)
        self.assertEqual(finding.risk_level, Finding.RiskLevel.HIGH)
        self.assertEqual(finding.condition, self.template.condition)
        recommendations = list(finding.recommendations.order_by("number"))
        self.assertEqual([item.number for item in recommendations], [1, 2])
        # 10 días hábiles desde el viernes 13 de noviembre; sin plazo, la fecha general.
        self.assertEqual(recommendations[0].deadline, date(2026, 11, 27))
        self.assertEqual(recommendations[1].deadline, date(2026, 12, 18))
        self.assertTrue(all(item.responsible_organization == self.center for item in recommendations))
        self.assertEqual(recommendations[0].evidence_requirements, "Conciliaciones firmadas.")
        self.assertTrue(
            ActivityLog.objects.filter(case=self.case, action="finding_created_from_template").exists()
        )

        # Cambiar la plantilla después no altera el hallazgo copiado.
        self.template.title = "Título nuevo"
        self.template.save()
        finding.refresh_from_db()
        self.assertEqual(finding.title, "Falta de conciliaciones bancarias")

    def test_template_use_respects_draft_scope_and_active_status(self):
        url = reverse("case_library_use", args=[self.case.pk, self.template.pk])
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(url).status_code, 405)

        self.client.force_login(self.other_auditor)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("case_library", args=[self.case.pk])).status_code, 403)

        self.client.force_login(self.auditor)
        self.template.is_active = False
        self.template.save()
        self.assertEqual(self.client.post(url).status_code, 404)

        self.template.is_active = True
        self.template.save()
        self.case.status = AuditCase.Status.PUBLISHED
        self.case.save(update_fields=["status"])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(self.case.findings.exists())

    def test_placeholders_left_from_a_template_block_publication(self):
        self.client.force_login(self.auditor)
        self.client.post(reverse("case_library_use", args=[self.case.pk, self.template.pk]))
        finding = self.case.findings.get()
        self.assertIn(
            "Reemplace los datos entre [corchetes] del hallazgo 1 y sus recomendaciones.",
            publication_issues(self.case),
        )
        builder = self.client.get(reverse("case_builder", args=[self.case.pk]))
        self.assertContains(builder, "Datos entre [corchetes]")
        self.assertContains(builder, "Gestión financiera")

        finding.condition = "Durante enero a junio de 2026 no se elaboraron conciliaciones."
        finding.save()
        self.assertFalse(any("corchetes" in issue for issue in publication_issues(self.case)))

    def test_brackets_in_handwritten_findings_are_not_flagged(self):
        Finding.objects.create(
            case=self.case, number=1, title="Hallazgo [redactado a mano]",
            risk_level=Finding.RiskLevel.LOW,
        )
        self.assertFalse(any("corchetes" in issue for issue in publication_issues(self.case)))

    def test_finding_area_is_required_only_once_the_catalog_exists(self):
        form = FindingForm()
        self.assertIn("category", form.fields)
        self.assertTrue(form.fields["category"].required)

        FindingCategory.objects.update(is_active=False)
        self.assertNotIn("category", FindingForm().fields)

        # Un hallazgo ya clasificado conserva su área aunque luego se desactive.
        FindingCategory.objects.create(name="Compras")
        finding = Finding.objects.create(
            case=self.case, number=1, title="X", risk_level=Finding.RiskLevel.LOW,
            category=self.category,
        )
        choices = FindingForm(instance=finding).fields["category"].queryset
        self.assertIn(self.category, choices)
        self.assertNotIn(self.category, FindingForm().fields["category"].queryset)

    def test_recommendation_form_marks_the_deadline_suggested_by_risk(self):
        finding = Finding.objects.create(
            case=self.case, number=1, title="Riesgo alto", risk_level=Finding.RiskLevel.HIGH
        )
        self.client.force_login(self.auditor)
        page = self.client.get(reverse("recommendation_create", args=[finding.pk]))
        self.assertContains(page, "15 días hábiles (sugerido)")
        self.assertNotContains(page, "10 días hábiles (sugerido)")
