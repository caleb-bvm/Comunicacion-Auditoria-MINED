import shutil
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import ActivityLog, AuditCase, AuditInquiry, AuditInquiryMessage


INQUIRY_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-consultas-test-")


@override_settings(MEDIA_ROOT=INQUIRY_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class AuditInquiryTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(INQUIRY_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.organization = Organization.objects.create(
            code="CE-100", name="Centro consultante",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.other_organization = Organization.objects.create(
            code="CE-200", name="Otro centro",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.institution = User.objects.create_user(
            username="CE-100", password="TestPass123!", role=User.Role.INSTITUTION,
            organization=self.organization, must_change_password=False,
        )
        self.other_institution = User.objects.create_user(
            username="CE-200", password="TestPass123!", role=User.Role.INSTITUTION,
            organization=self.other_organization, must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor.consultas", password="TestPass123!", role=User.Role.AUDITOR,
            must_change_password=False,
        )
        self.other_auditor = User.objects.create_user(
            username="auditor.otro", password="TestPass123!", role=User.Role.AUDITOR,
            must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="direccion.consultas", password="TestPass123!", role=User.Role.AUDIT_MANAGER,
            must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="AUD-C-001", title="Auditoría de prueba",
            audited_organization=self.organization, assigned_auditor=self.auditor,
            created_by=self.auditor, status=AuditCase.Status.PUBLISHED,
        )

    def create_inquiry(self):
        inquiry = AuditInquiry.objects.create(
            case=self.case, organization=self.organization, subject="Consulta de plazos",
            category=AuditInquiry.Category.DEADLINES,
            assigned_auditor=self.auditor, created_by=self.institution,
        )
        AuditInquiryMessage.objects.create(
            inquiry=inquiry, author=self.institution, body="¿Cuál es el plazo aplicable?",
        )
        return inquiry

    def test_institution_creates_inquiry_routed_to_case_auditor(self):
        self.client.force_login(self.institution)
        response = self.client.post(reverse("audit_inquiry_create"), {
            "case": self.case.pk,
            "category": AuditInquiry.Category.DEADLINES,
            "subject": "Duda sobre el plazo",
            "priority": AuditInquiry.Priority.HIGH,
            "body": "Necesitamos confirmar la fecha de presentación.",
        })
        self.assertFalse(response.context and response.context["form"].errors,
                         response.context["form"].errors if response.context else response.status_code)
        inquiry = AuditInquiry.objects.get()
        self.assertRedirects(response, reverse("audit_inquiry_detail", args=[inquiry.pk]))
        self.assertEqual(inquiry.organization, self.organization)
        self.assertEqual(inquiry.assigned_auditor, self.auditor)
        self.assertEqual(inquiry.messages.get().author, self.institution)
        self.assertTrue(ActivityLog.objects.filter(action="audit_inquiry_created").exists())

    def test_other_institution_and_unassigned_auditor_cannot_open_inquiry(self):
        inquiry = self.create_inquiry()
        for user in (self.other_institution, self.other_auditor):
            self.client.force_login(user)
            response = self.client.get(reverse("audit_inquiry_detail", args=[inquiry.pk]))
            self.assertEqual(response.status_code, 404)

    def test_assigned_auditor_answer_marks_inquiry_answered(self):
        inquiry = self.create_inquiry()
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("audit_inquiry_detail", args=[inquiry.pk]),
            {"body": "El plazo consta en el expediente."},
        )
        self.assertRedirects(response, reverse("audit_inquiry_detail", args=[inquiry.pk]))
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, AuditInquiry.Status.ANSWERED)
        self.assertEqual(inquiry.messages.count(), 2)

    def test_institution_can_close_answered_inquiry(self):
        inquiry = self.create_inquiry()
        inquiry.status = AuditInquiry.Status.ANSWERED
        inquiry.save(update_fields=["status"])
        self.client.force_login(self.institution)
        response = self.client.post(reverse("audit_inquiry_close", args=[inquiry.pk]))
        self.assertRedirects(response, reverse("audit_inquiry_detail", args=[inquiry.pk]))
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.status, AuditInquiry.Status.CLOSED)
        self.assertIsNotNone(inquiry.closed_at)

    def test_director_can_reassign_and_change_status(self):
        inquiry = self.create_inquiry()
        self.client.force_login(self.director)
        response = self.client.post(reverse("audit_inquiry_manage", args=[inquiry.pk]), {
            "status": AuditInquiry.Status.IN_PROGRESS,
            "assigned_auditor": self.other_auditor.pk,
            "note": "Redistribución de carga",
        })
        self.assertRedirects(response, reverse("audit_inquiry_detail", args=[inquiry.pk]))
        inquiry.refresh_from_db()
        self.assertEqual(inquiry.assigned_auditor, self.other_auditor)
        self.assertEqual(inquiry.status, AuditInquiry.Status.IN_PROGRESS)
        self.assertTrue(ActivityLog.objects.filter(action="audit_inquiry_managed").exists())
