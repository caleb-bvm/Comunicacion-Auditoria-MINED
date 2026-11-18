import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import ActivityLog, AuditCase, Evidence, Finding, FindingCategory, Recommendation, Response

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-fase3-")


class Phase3Base(TestCase):
    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.other_center = Organization.objects.create(
            code="10755", name="Centro Dos", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.auditor.assigned_organizations.add(self.center, self.other_center)
        self.other_auditor = User.objects.create_user(
            username="otro-auditor", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.institution = User.objects.create_user(
            username="10754", role=User.Role.INSTITUTION, organization=self.center,
            must_change_password=False,
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class EvidenceChecklistTests(Phase3Base):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.case = AuditCase.objects.create(
            reference="IA-F3-001", title="Fondos", audited_organization=self.center,
            status=AuditCase.Status.PUBLISHED, assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        finding = Finding.objects.create(
            case=self.case, number=1, title="Conciliaciones", risk_level=Finding.RiskLevel.HIGH
        )
        self.recommendation = Recommendation.objects.create(
            finding=finding, number=1, text="Elabore las conciliaciones.",
            responsible_organization=self.center, deadline=date(2099, 1, 1),
            evidence_requirements="- Conciliaciones firmadas.\nEstados de cuenta\nActa del CDE",
        )

    def submit(self, **extra):
        payload = {
            "declared_status": Response.DeclaredStatus.COMPLETED,
            "action_description": "Se elaboraron las conciliaciones.",
            "action_date": date(2026, 11, 10).isoformat(),
            "responsible_name": "Directora",
            "responsible_job_title": "Dirección",
            "accuracy_declaration": "on",
            "evidence_category": Evidence.Category.BANKING,
            "evidence_description": "Conciliaciones y estados de cuenta.",
            "files": SimpleUploadedFile("conciliaciones.pdf", b"%PDF-1.4\nprueba", content_type="application/pdf"),
        }
        payload.update(extra)
        self.client.force_login(self.institution)
        return self.client.post(
            reverse("respond_recommendation", args=[self.recommendation.pk]), payload
        )

    def test_institution_sees_requested_documents_as_checkboxes(self):
        self.client.force_login(self.institution)
        page = self.client.get(reverse("respond_recommendation", args=[self.recommendation.pk]))
        self.assertContains(page, 'name="covered_requirements"', count=3)
        self.assertContains(page, 'value="Conciliaciones firmadas."')

    def test_marked_documents_are_stored_in_requested_order(self):
        result = self.submit(covered_requirements=["Acta del CDE", "Conciliaciones firmadas."])
        self.assertRedirects(result, reverse("case_detail", args=[self.case.pk]))
        response = self.recommendation.responses.get()
        self.assertEqual(response.covered_requirements, ["Conciliaciones firmadas.", "Acta del CDE"])

    def test_unknown_documents_are_rejected(self):
        result = self.submit(covered_requirements=["Documento inventado"])
        self.assertEqual(result.status_code, 200)
        self.assertFalse(self.recommendation.responses.exists())

    def test_review_shows_which_documents_were_marked(self):
        self.submit(covered_requirements=["Estados de cuenta"])
        response = self.recommendation.responses.get()
        self.client.force_login(self.auditor)
        page = self.client.get(reverse("review_response", args=[response.pk]))
        self.assertContains(page, "marcó 1 como incluido")
        self.assertContains(page, "el centro indica que lo incluyó", count=1)
        self.assertContains(page, "no lo marcó como incluido", count=2)

    def test_older_responses_without_checklist_show_the_plain_list(self):
        response = Response.objects.create(
            recommendation=self.recommendation, version=1,
            declared_status=Response.DeclaredStatus.COMPLETED, action_description="Hecho.",
            responsible_name="A", responsible_job_title="B", accuracy_declaration=True,
            submitted_by=self.institution,
        )
        self.client.force_login(self.auditor)
        page = self.client.get(reverse("review_response", args=[response.pk]))
        self.assertNotContains(page, "no lo marcó como incluido")
        self.assertContains(page, "Estados de cuenta")

    def test_recommendation_without_requirements_has_no_checklist(self):
        self.recommendation.evidence_requirements = ""
        self.recommendation.save()
        self.client.force_login(self.institution)
        page = self.client.get(reverse("respond_recommendation", args=[self.recommendation.pk]))
        self.assertNotContains(page, 'name="covered_requirements"')
        self.submit()
        self.assertIsNone(self.recommendation.responses.get().covered_requirements)


class CopyFromPreviousCaseTests(Phase3Base):
    def setUp(self):
        super().setUp()
        self.category = FindingCategory.objects.create(name="Gestión financiera")
        self.previous = AuditCase.objects.create(
            reference="IA-F3-ANTERIOR", title="Examen anterior", audited_organization=self.other_center,
            status=AuditCase.Status.CLOSED, assigned_auditor=self.auditor, created_by=self.auditor,
        )
        self.source = Finding.objects.create(
            case=self.previous, number=4, title="Caja chica sin arqueos",
            risk_level=Finding.RiskLevel.MEDIUM, category=self.category,
            condition="En 2025 no hubo arqueos.", criteria="Norma.", cause="Causa.", effect="Efecto.",
        )
        Recommendation.objects.create(
            finding=self.source, number=2, text="Realice arqueos mensuales.",
            responsible_organization=self.other_center, deadline=date(2025, 6, 1),
            evidence_requirements="Actas de arqueo.",
        )
        foreign_case = AuditCase.objects.create(
            reference="IA-F3-AJENO", title="De otro auditor", audited_organization=self.center,
            status=AuditCase.Status.CLOSED, assigned_auditor=self.other_auditor,
            created_by=self.other_auditor,
        )
        self.foreign = Finding.objects.create(
            case=foreign_case, number=1, title="Hallazgo reservado", risk_level=Finding.RiskLevel.LOW
        )
        self.draft = AuditCase.objects.create(
            reference="IA-F3-BORRADOR", title="Nuevo examen", audited_organization=self.center,
            status=AuditCase.Status.DRAFT, assigned_auditor=self.auditor, created_by=self.auditor,
            response_deadline=date(2026, 12, 18),
        )
        self.client.force_login(self.auditor)

    def test_lists_only_the_auditors_own_findings_from_other_cases(self):
        Finding.objects.create(
            case=self.draft, number=1, title="Hallazgo del mismo borrador", risk_level=Finding.RiskLevel.LOW
        )
        page = self.client.get(reverse("case_copy_previous", args=[self.draft.pk]))
        self.assertContains(page, "Caja chica sin arqueos")
        self.assertContains(page, "IA-F3-ANTERIOR")
        self.assertNotContains(page, "Hallazgo reservado")
        self.assertNotContains(page, "Hallazgo del mismo borrador")
        page = self.client.get(reverse("case_copy_previous", args=[self.draft.pk]), {"q": "Centro Dos"})
        self.assertContains(page, "Caja chica sin arqueos")
        page = self.client.get(reverse("case_copy_previous", args=[self.draft.pk]), {"q": "inexistente"})
        self.assertNotContains(page, "Caja chica sin arqueos")

    def test_copy_creates_an_independent_finding_for_the_current_center(self):
        result = self.client.post(
            reverse("case_copy_previous_use", args=[self.draft.pk, self.source.pk])
        )
        copy = self.draft.findings.get()
        self.assertRedirects(result, reverse("finding_edit", args=[copy.pk]))
        self.assertEqual(copy.number, 1)
        self.assertEqual(copy.title, "Caja chica sin arqueos")
        self.assertEqual(copy.category, self.category)
        self.assertIsNone(copy.source_template)
        recommendation = copy.recommendations.get()
        self.assertEqual(recommendation.number, 1)
        self.assertEqual(recommendation.responsible_organization, self.center)
        self.assertEqual(recommendation.deadline, date(2026, 12, 18))
        self.assertEqual(recommendation.evidence_requirements, "Actas de arqueo.")
        self.assertEqual(recommendation.status, Recommendation.Status.PENDING)
        log = ActivityLog.objects.get(case=self.draft, action="finding_copied_from_case")
        self.assertEqual(log.details["source_case"], "IA-F3-ANTERIOR")
        self.source.refresh_from_db()
        self.assertEqual(self.source.recommendations.get().deadline, date(2025, 6, 1))

    def test_cannot_copy_another_auditors_finding_or_into_a_foreign_draft(self):
        result = self.client.post(
            reverse("case_copy_previous_use", args=[self.draft.pk, self.foreign.pk])
        )
        self.assertEqual(result.status_code, 404)
        self.client.force_login(self.other_auditor)
        result = self.client.post(
            reverse("case_copy_previous_use", args=[self.draft.pk, self.source.pk])
        )
        self.assertEqual(result.status_code, 403)
        self.assertEqual(
            self.client.get(reverse("case_copy_previous", args=[self.draft.pk])).status_code, 403
        )
        self.assertFalse(self.draft.findings.exists())


class AutosaveMarkupTests(Phase3Base):
    def test_long_forms_opt_into_autosave_and_logout_clears_drafts(self):
        draft = AuditCase.objects.create(
            reference="IA-F3-AUTO", title="Borrador", audited_organization=self.center,
            status=AuditCase.Status.DRAFT, assigned_auditor=self.auditor, created_by=self.auditor,
        )
        self.client.force_login(self.auditor)
        page = self.client.get(reverse("finding_create", args=[draft.pk]))
        self.assertContains(page, "data-autosave")
        self.assertContains(page, "data-clear-drafts", count=2)
