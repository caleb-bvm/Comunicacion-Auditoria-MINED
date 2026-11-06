import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import AuditCase, Evidence, Finding, Recommendation, Response, Review


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-auditor-ui-")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class AuditorScreensTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            first_name="Sandra",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        self.auditor.assigned_organizations.add(self.center)
        institution_user = User.objects.create_user(
            username="10754",
            role=User.Role.INSTITUTION,
            organization=self.center,
            must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="IA-200",
            title="Otros ingresos",
            audited_organization=self.center,
            status=AuditCase.Status.UNDER_REVIEW,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        finding = Finding.objects.create(
            case=self.case, number=1, title="Hallazgo", risk_level=Finding.RiskLevel.HIGH
        )
        self.recommendation = Recommendation.objects.create(
            finding=finding,
            number=3,
            text="Deposite los fondos en la cuenta bancaria.",
            responsible_organization=self.center,
            deadline=timezone.localdate() + timedelta(days=20),
            evidence_requirements="Comprobantes de depósito\nEstado de cuenta\nConciliación firmada",
            status=Recommendation.Status.SUBMITTED,
        )
        self.response = Response.objects.create(
            recommendation=self.recommendation,
            version=1,
            declared_status=Response.DeclaredStatus.COMPLETED,
            action_description="Se depositaron los fondos.",
            action_date=timezone.localdate(),
            responsible_name="Dirección",
            responsible_job_title="Director",
            accuracy_declaration=True,
            submitted_by=institution_user,
        )
        Evidence.objects.create(
            response=self.response,
            file=SimpleUploadedFile("acta.pdf", b"%PDF-1.4 prueba", content_type="application/pdf"),
            original_filename="acta.pdf",
            category=Evidence.Category.MINUTES,
            description="Acta",
            sha256="0" * 64,
            uploaded_by=institution_user,
        )
        self.client.force_login(self.auditor)

    def test_home_lists_reviews_first_with_one_filled_button(self):
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Para revisar · 1")
        self.assertContains(page, "Centro Uno · Rec. 1.3")
        self.assertContains(page, reverse("review_response", args=[self.response.pk]))
        self.assertContains(page, "ui-button-filled", count=1)

    def test_case_list_says_what_comes_next(self):
        page = self.client.get(reverse("case_list"))
        self.assertContains(page, "Mi cartera")
        self.assertContains(page, "Qué sigue")
        self.assertContains(page, reverse("review_response", args=[self.response.pk]))
        self.assertContains(page, "IA-200 · 10754 · Otros ingresos")
        self.assertContains(page, 'aria-label="Buscar expedientes"')

    def test_review_page_compares_request_and_answer(self):
        page = self.client.get(reverse("review_response", args=[self.response.pk]))
        self.assertContains(page, "El centro dice «Completada» y envió 1 documento; se pidieron 3.")
        self.assertContains(page, "Se pidió")
        self.assertContains(page, "Respondió")
        self.assertContains(page, "Conciliación firmada")
        self.assertContains(page, "Pedir corrección")
        self.assertContains(page, 'type="radio" name="outcome"')
        self.assertNotContains(page, "---------")

    def test_review_still_records_the_outcome(self):
        result = self.client.post(
            reverse("review_response", args=[self.response.pk]),
            {"outcome": Review.Outcome.CORRECTION_REQUIRED, "comments": "Adjunte la conciliación."},
        )
        self.assertRedirects(result, reverse("case_detail", args=[self.case.pk]))
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.CORRECTION_REQUIRED)
