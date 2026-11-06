from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import AuditCase, Finding, Recommendation, Response, Review


class InstitutionTaskScreensTests(TestCase):
    def setUp(self):
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            first_name="NombreReservado",
            role=User.Role.AUDITOR,
            organization=audit_unit,
            must_change_password=False,
        )
        self.institution_user = User.objects.create_user(
            username="10754",
            role=User.Role.INSTITUTION,
            organization=self.center,
            must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="IA-100",
            title="Auditoría de prueba",
            audited_organization=self.center,
            status=AuditCase.Status.IN_RESPONSE,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        finding = Finding.objects.create(
            case=self.case, number=1, title="Hallazgo", risk_level=Finding.RiskLevel.HIGH
        )
        self.recommendation = Recommendation.objects.create(
            finding=finding,
            number=1,
            text="Actualice y firme las actas de asignación.",
            responsible_organization=self.center,
            deadline=timezone.localdate() - timedelta(days=10),
            evidence_requirements="- Actas firmadas\n- Inventario actualizado",
            status=Recommendation.Status.CORRECTION_REQUIRED,
        )
        response = Response.objects.create(
            recommendation=self.recommendation,
            version=1,
            declared_status=Response.DeclaredStatus.IN_PROGRESS,
            action_description="Se actualizó el formato.",
            responsible_name="Dirección",
            responsible_job_title="Director",
            accuracy_declaration=True,
            submitted_by=self.institution_user,
        )
        Review.objects.create(
            response=response,
            outcome=Review.Outcome.CORRECTION_REQUIRED,
            comments="Adjunte las cinco actas firmadas.",
            reviewed_by=self.auditor,
        )
        self.client.force_login(self.institution_user)

    def test_home_shows_task_with_status_deadline_and_audit_request(self):
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Para hacer · 1")
        self.assertContains(page, "ui-chip-correction")
        self.assertContains(page, "Venció el")
        self.assertContains(page, "Auditoría pide: Adjunte las cinco actas firmadas.")
        self.assertContains(page, "Corregir respuesta")
        self.assertNotContains(page, "NombreReservado")

    def test_respond_page_shows_audit_request_steps_and_requirements(self):
        page = self.client.get(reverse("respond_recommendation", args=[self.recommendation.pk]))
        self.assertContains(page, "Lo que pide Auditoría")
        self.assertContains(page, "Adjunte las cinco actas firmadas.")
        self.assertContains(page, "Actas firmadas")
        self.assertContains(page, "Inventario actualizado")
        self.assertContains(page, 'type="radio" name="declared_status"')
        self.assertNotContains(page, "---------")
        self.assertContains(page, "Hasta 20 MB cada uno.")
        self.assertNotContains(page, "NombreReservado")
