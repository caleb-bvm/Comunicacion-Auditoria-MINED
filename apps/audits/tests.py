import hashlib
import shutil
import tempfile
from datetime import date, timedelta
from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import load_workbook

from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.validators import validate_evidence_file
from apps.institutions.models import Organization, SchoolBoardPeriod

from .models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    BusinessDayHoliday,
    CaseDecision,
    DeadlineExtension,
    Evidence,
    Finding,
    HistoricalRecommendation,
    Recommendation,
    Response,
    Review,
)
from .services import add_business_days, mark_overdue_recommendations


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-test-")
SEED_TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-seed-test-")


def make_docx_upload(filename="informe.docx"):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        )
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )
    return SimpleUploadedFile(
        filename,
        buffer.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


@override_settings(MEDIA_ROOT=SEED_TEST_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class SeedDemoCommandTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(SEED_TEST_MEDIA_ROOT, ignore_errors=True)

    def test_running_seed_again_preserves_existing_passwords(self):
        call_command("seed_demo", stdout=StringIO())
        original_passwords = dict(
            User.objects.filter(
                username__in=["auditor.demo", "directora.demo", "10754"]
            )
            .values_list("username", "password")
        )

        output = StringIO()
        call_command("seed_demo", stdout=output)

        current_passwords = dict(
            User.objects.filter(
                username__in=["auditor.demo", "directora.demo", "10754"]
            )
            .values_list("username", "password")
        )
        self.assertEqual(current_passwords, original_passwords)
        self.assertIn("se conservó la contraseña existente", output.getvalue())

    def test_passwords_can_be_reset_explicitly(self):
        call_command("seed_demo", stdout=StringIO())
        original_passwords = dict(
            User.objects.filter(
                username__in=["auditor.demo", "directora.demo", "10754"]
            )
            .values_list("username", "password")
        )

        output = StringIO()
        call_command("seed_demo", reset_passwords=True, stdout=output)

        current_passwords = dict(
            User.objects.filter(
                username__in=["auditor.demo", "directora.demo", "10754"]
            )
            .values_list("username", "password")
        )
        self.assertNotEqual(current_passwords, original_passwords)
        self.assertIn("Auditoría: auditor.demo /", output.getvalue())
        self.assertIn("Dirección: directora.demo /", output.getvalue())

    def test_seed_creates_complete_scenarios_for_all_demo_roles(self):
        output = StringIO()
        call_command("seed_demo", stdout=output)

        publication_case = AuditCase.objects.get(reference="IA/NA-011-2026")
        self.assertEqual(publication_case.status, AuditCase.Status.PENDING_PUBLICATION)
        self.assertEqual(publication_case.findings.count(), 2)
        self.assertEqual(
            Recommendation.objects.filter(finding__case=publication_case).count(),
            2,
        )
        self.assertFalse(
            publication_case.findings.filter(
                condition="", criteria="", cause="", effect=""
            ).exists()
        )
        publication_decision = CaseDecision.objects.get(
            case=publication_case,
            kind=CaseDecision.Kind.PUBLICATION,
            status=CaseDecision.Status.PENDING,
        )
        self.assertTrue(publication_decision.request_note)
        self.assertEqual(publication_decision.requested_by.username, "auditor.demo")
        self.assertEqual(
            publication_decision.document.status,
            AuditDocument.Status.PENDING_APPROVAL,
        )
        self.assertEqual(
            publication_decision.document.visibility,
            AuditDocument.Visibility.AUDIT_ONLY,
        )
        self.assertTrue(publication_decision.document.file.storage.exists(
            publication_decision.document.file.name
        ))

        response_case = AuditCase.objects.get(reference="IA/NA-010-2025")
        self.assertEqual(response_case.status, AuditCase.Status.PUBLISHED)
        self.assertTrue(
            Recommendation.objects.filter(
                finding__case=response_case,
                responsible_organization__code="10754",
                status=Recommendation.Status.PENDING,
            ).exists()
        )

        review_case = AuditCase.objects.get(reference="IA/NA-009-2025")
        pending_response = Response.objects.get(recommendation__finding__case=review_case)
        self.assertEqual(review_case.status, AuditCase.Status.UNDER_REVIEW)
        self.assertFalse(hasattr(pending_response, "review"))
        self.assertTrue(pending_response.evidence.exists())

        correction_case = AuditCase.objects.get(reference="IA/NA-008-2025")
        correction_response = Response.objects.get(
            recommendation__finding__case=correction_case
        )
        self.assertEqual(correction_case.status, AuditCase.Status.CORRECTION_REQUIRED)
        self.assertEqual(
            correction_response.review.outcome,
            Review.Outcome.CORRECTION_REQUIRED,
        )

        closure_case = AuditCase.objects.get(reference="IA/NA-007-2024")
        self.assertEqual(closure_case.status, AuditCase.Status.PENDING_CLOSURE)
        self.assertTrue(
            CaseDecision.objects.filter(
                case=closure_case,
                kind=CaseDecision.Kind.CLOSURE,
                status=CaseDecision.Status.PENDING,
            ).exists()
        )
        self.assertFalse(
            Recommendation.objects.filter(finding__case=closure_case).exclude(
                status__in=[
                    Recommendation.Status.COMPLIED,
                    Recommendation.Status.PARTIAL,
                    Recommendation.Status.NOT_COMPLIED,
                ]
            ).exists()
        )
        self.assertIn("Escenarios disponibles", output.getvalue())

    def test_seed_adds_two_source_based_centers_ready_for_activation(self):
        output = StringIO()
        call_command("seed_demo", stdout=output)

        expected_centers = {
            "10471": (
                "Centro Escolar Florinda B. González",
                "Santa Ana",
                "Santa Ana Centro",
            ),
            "11489": (
                "Complejo Educativo Comunidad 10 de Octubre",
                "San Salvador",
                "San Salvador Sur",
            ),
        }
        for code, (name, department, municipality) in expected_centers.items():
            center = Organization.objects.get(code=code)
            self.assertEqual(center.name, name)
            self.assertEqual(center.department, department)
            self.assertEqual(center.municipality, municipality)
            self.assertTrue(center.is_active)
            self.assertFalse(
                User.objects.filter(
                    organization=center,
                    role=User.Role.INSTITUTION,
                ).exists()
            )

        florinda_case = AuditCase.objects.get(reference="IA/NA-043-2024")
        self.assertEqual(florinda_case.audited_organization.code, "10471")
        self.assertEqual(florinda_case.status, AuditCase.Status.PUBLISHED)
        self.assertEqual(florinda_case.report_date, date(2025, 2, 25))
        self.assertEqual(florinda_case.findings.count(), 4)
        self.assertEqual(
            Recommendation.objects.filter(finding__case=florinda_case).count(),
            4,
        )

        comunidad_case = AuditCase.objects.get(reference="IA/NA-046-2024")
        self.assertEqual(comunidad_case.audited_organization.code, "11489")
        self.assertEqual(comunidad_case.status, AuditCase.Status.PUBLISHED)
        self.assertEqual(comunidad_case.report_date, date(2025, 4, 1))
        self.assertEqual(comunidad_case.findings.count(), 4)
        self.assertEqual(
            Recommendation.objects.filter(finding__case=comunidad_case).count(),
            4,
        )
        low_enrollment = comunidad_case.findings.get(number=6).recommendations.get(
            number=1
        )
        self.assertEqual(
            low_enrollment.responsible_organization.code,
            "DDE-SAN-SALVADOR",
        )

        director = User.objects.get(username="directora.demo")
        self.client.force_login(director)
        directory = self.client.get(
            reverse("director_educational_centers"),
            {"q": "10471"},
        )
        self.assertContains(directory, "Centro Escolar Florinda B. González")
        self.assertContains(directory, "Activar acceso por correo")
        center_cases = self.client.get(
            reverse("case_list"),
            {"organization": florinda_case.audited_organization_id},
        )
        self.assertContains(center_cases, "IA/NA-043-2024")
        self.assertNotContains(center_cases, "IA/NA-046-2024")
        self.assertIn("IA/NA-043-2024 e IA/NA-046-2024", output.getvalue())

    def test_seeded_roles_receive_actionable_and_scoped_dashboards(self):
        call_command("seed_demo", stdout=StringIO())
        director = User.objects.get(username="directora.demo")
        auditor = User.objects.get(username="auditor.demo")
        institution = User.objects.get(username="10754")

        self.client.force_login(director)
        director_dashboard = self.client.get(reverse("director_dashboard"))
        self.assertContains(director_dashboard, "IA/NA-011-2026")
        self.assertContains(director_dashboard, "IA/NA-007-2024")

        publication_case = AuditCase.objects.get(reference="IA/NA-011-2026")
        self.client.force_login(auditor)
        auditor_detail = self.client.get(reverse("case_detail", args=[publication_case.pk]))
        self.assertEqual(auditor_detail.status_code, 200)
        self.assertContains(auditor_detail, "Expedientes de compra con documentación incompleta")

        response_case = AuditCase.objects.get(reference="IA/NA-010-2025")
        self.client.force_login(institution)
        hidden_publication = self.client.get(reverse("case_detail", args=[publication_case.pk]))
        visible_response_case = self.client.get(reverse("case_detail", args=[response_case.pk]))
        self.assertEqual(hidden_publication.status_code, 404)
        self.assertContains(visible_response_case, "Presentar respuesta")

    def test_running_seed_again_does_not_duplicate_demo_workflow(self):
        call_command("seed_demo", stdout=StringIO())
        references = [
            "IA/NA-007-2024",
            "IA/NA-043-2024",
            "IA/NA-046-2024",
            "IA/NA-008-2025",
            "IA/NA-009-2025",
            "IA/NA-010-2025",
            "IA/NA-011-2026",
        ]
        first_counts = {
            "cases": AuditCase.objects.filter(reference__in=references).count(),
            "documents": AuditDocument.objects.filter(case__reference__in=references).count(),
            "findings": Finding.objects.filter(case__reference__in=references).count(),
            "recommendations": Recommendation.objects.filter(
                finding__case__reference__in=references
            ).count(),
            "decisions": CaseDecision.objects.filter(case__reference__in=references).count(),
            "responses": Response.objects.filter(
                recommendation__finding__case__reference__in=references
            ).count(),
            "evidence": Evidence.objects.filter(
                response__recommendation__finding__case__reference__in=references
            ).count(),
            "reviews": Review.objects.filter(
                response__recommendation__finding__case__reference__in=references
            ).count(),
            "activity": ActivityLog.objects.filter(case__reference__in=references).count(),
        }

        call_command("seed_demo", stdout=StringIO())

        second_counts = {
            "cases": AuditCase.objects.filter(reference__in=references).count(),
            "documents": AuditDocument.objects.filter(case__reference__in=references).count(),
            "findings": Finding.objects.filter(case__reference__in=references).count(),
            "recommendations": Recommendation.objects.filter(
                finding__case__reference__in=references
            ).count(),
            "decisions": CaseDecision.objects.filter(case__reference__in=references).count(),
            "responses": Response.objects.filter(
                recommendation__finding__case__reference__in=references
            ).count(),
            "evidence": Evidence.objects.filter(
                response__recommendation__finding__case__reference__in=references
            ).count(),
            "reviews": Review.objects.filter(
                response__recommendation__finding__case__reference__in=references
            ).count(),
            "activity": ActivityLog.objects.filter(case__reference__in=references).count(),
        }
        self.assertEqual(second_counts, first_counts)
        self.assertEqual(first_counts["cases"], 7)
        self.assertEqual(first_counts["decisions"], 2)

    def test_reseeding_after_review_preserves_history_and_restores_a_pending_review(self):
        call_command("seed_demo", stdout=StringIO())
        auditor = User.objects.get(username="auditor.demo")
        review_case = AuditCase.objects.get(reference="IA/NA-009-2025")
        original_response = Response.objects.get(recommendation__finding__case=review_case)
        Review.objects.create(
            response=original_response,
            outcome=Review.Outcome.COMPLIED,
            comments="Revisión realizada durante la demostración.",
            reviewed_by=auditor,
        )

        call_command("seed_demo", stdout=StringIO())

        responses = Response.objects.filter(
            recommendation__finding__case=review_case
        ).order_by("version")
        self.assertEqual(list(responses.values_list("version", flat=True)), [1, 2])
        self.assertTrue(hasattr(responses[0], "review"))
        self.assertFalse(hasattr(responses[1], "review"))
        self.assertTrue(responses[1].evidence.exists())

    def test_seeded_publication_can_be_approved_answered_and_reviewed(self):
        call_command("seed_demo", stdout=StringIO())
        director = User.objects.get(username="directora.demo")
        auditor = User.objects.get(username="auditor.demo")
        institution = User.objects.get(username="10754")
        publication_case = AuditCase.objects.get(reference="IA/NA-011-2026")
        decision = publication_case.decisions.get(status=CaseDecision.Status.PENDING)

        self.client.force_login(director)
        approval = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]),
            {
                "action": "approve",
                "justification": "El informe contiene contexto y evidencia suficientes para publicarse.",
            },
        )
        self.assertRedirects(approval, reverse("director_decisions"))
        publication_case.refresh_from_db()
        self.assertEqual(publication_case.status, AuditCase.Status.PUBLISHED)

        recommendation = Recommendation.objects.filter(
            finding__case=publication_case,
            responsible_organization=institution.organization,
            status=Recommendation.Status.PENDING,
        ).first()
        self.assertIsNotNone(recommendation)
        self.client.force_login(institution)
        submission = self.client.post(
            reverse("respond_recommendation", args=[recommendation.pk]),
            {
                "declared_status": Response.DeclaredStatus.COMPLETED,
                "action_description": "Se completó el expediente y se aprobó la lista de control.",
                "action_date": date.today().isoformat(),
                "responsible_name": "Responsable Institucional",
                "responsible_job_title": "Dirección del centro educativo",
                "accuracy_declaration": "on",
                "evidence_category": Evidence.Category.MINUTES,
                "evidence_description": "Acta y lista de control aprobadas.",
                "files": SimpleUploadedFile(
                    "acta-lista-control.pdf",
                    b"%PDF-1.4\ndocumento de prueba",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertRedirects(submission, reverse("case_detail", args=[publication_case.pk]))
        submitted_response = recommendation.responses.get(version=1)

        self.client.force_login(auditor)
        review = self.client.post(
            reverse("review_response", args=[submitted_response.pk]),
            {
                "outcome": Review.Outcome.COMPLIED,
                "comments": "La evidencia presentada atiende completamente la recomendación.",
            },
        )
        self.assertRedirects(review, reverse("case_detail", args=[publication_case.pk]))
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, Recommendation.Status.COMPLIED)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class AccessAndWorkflowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.center = Organization.objects.create(
            code="CE-1", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.other_center = Organization.objects.create(
            code="CE-2", name="Centro Dos", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.audit_unit = Organization.objects.create(
            code="DAI", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="directora",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDIT_MANAGER,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.technical_admin = User.objects.create_user(
            username="tecnico",
            password="UnaClaveDePrueba!2026",
            role=User.Role.TECHNICAL_ADMIN,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.institution_user = User.objects.create_user(
            username="centro1",
            password="UnaClaveDePrueba!2026",
            role=User.Role.INSTITUTION,
            organization=self.center,
            must_change_password=False,
        )
        self.other_user = User.objects.create_user(
            username="centro2",
            password="UnaClaveDePrueba!2026",
            role=User.Role.INSTITUTION,
            organization=self.other_center,
            must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="IA-001",
            title="Auditoría de prueba",
            audited_organization=self.center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.finding = Finding.objects.create(
            case=self.case, number=1, title="Hallazgo de prueba", risk_level=Finding.RiskLevel.HIGH
        )
        self.recommendation = Recommendation.objects.create(
            finding=self.finding,
            number=1,
            text="Registrar y documentar las operaciones.",
            responsible_organization=self.center,
            deadline=date.today(),
            evidence_requirements="Acta y registro actualizado.",
        )

    def test_password_is_hashed_with_argon2(self):
        self.assertEqual(identify_hasher(self.institution_user.password).algorithm, "argon2")

    def test_user_cannot_open_another_organizations_case(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(response.status_code, 404)

    def test_responsible_organization_can_open_case_detail(self):
        self.client.force_login(self.institution_user)
        response = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertContains(response, "Presentar respuesta")

    def test_institution_case_detail_hides_auditor_identity(self):
        self.auditor.first_name = "NombreReservado"
        self.auditor.last_name = "Auditor"
        self.auditor.save(update_fields=["first_name", "last_name"])

        self.client.force_login(self.institution_user)
        response = self.client.get(reverse("case_detail", args=[self.case.pk]))

        self.assertNotContains(response, "Auditor responsable")
        self.assertNotContains(response, "NombreReservado Auditor")

    def test_pending_recommendation_for_another_organization_explains_missing_response_button(self):
        Recommendation.objects.create(
            finding=self.finding,
            number=2,
            text="Coordinar el seguimiento departamental.",
            responsible_organization=self.other_center,
            deadline=date.today(),
        )

        self.client.force_login(self.institution_user)
        response = self.client.get(reverse("case_detail", args=[self.case.pk]))

        self.assertContains(
            response,
            f"La respuesta debe ser presentada por {self.other_center.name}.",
        )
        self.assertEqual(response.content.decode().count("Presentar respuesta"), 1)

    def test_responsible_organization_can_submit_response_and_evidence(self):
        cde_period = SchoolBoardPeriod.objects.create(
            organization=self.center,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            school_year_start=2026,
            school_year_end=2027,
            supporting_document=SimpleUploadedFile(
                "acta-cde.pdf",
                b"%PDF-1.4\nacta de prueba",
                content_type="application/pdf",
            ),
            supporting_document_name="acta-cde.pdf",
            created_by=self.institution_user,
            updated_by=self.institution_user,
        )
        self.client.force_login(self.institution_user)
        evidence = SimpleUploadedFile("acta.pdf", b"%PDF-1.4\ncontenido de prueba", content_type="application/pdf")
        response = self.client.post(
            reverse("respond_recommendation", args=[self.recommendation.pk]),
            {
                "declared_status": Response.DeclaredStatus.COMPLETED,
                "action_description": "Se actualizaron los registros.",
                "action_date": date.today().isoformat(),
                "responsible_name": "Responsable Uno",
                "responsible_job_title": "Director",
                "accuracy_declaration": "on",
                "evidence_category": Evidence.Category.MINUTES,
                "evidence_description": "Acta que acredita el acuerdo.",
                "files": evidence,
            },
        )
        self.assertRedirects(response, reverse("case_detail", args=[self.case.pk]))
        created = Response.objects.get(recommendation=self.recommendation)
        self.assertEqual(created.version, 1)
        self.assertEqual(created.school_board_period, cde_period)
        self.assertEqual(created.evidence.count(), 1)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.SUBMITTED)

    def test_response_cannot_be_submitted_without_document(self):
        self.client.force_login(self.institution_user)
        response = self.client.post(
            reverse("respond_recommendation", args=[self.recommendation.pk]),
            {
                "declared_status": Response.DeclaredStatus.COMPLETED,
                "action_description": "Se actualizaron los registros.",
                "action_date": date.today().isoformat(),
                "responsible_name": "Responsable Uno",
                "responsible_job_title": "Director",
                "accuracy_declaration": "on",
                "evidence_category": Evidence.Category.MINUTES,
                "evidence_description": "Acta que acredita el acuerdo.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Este campo es obligatorio")
        self.assertFalse(Response.objects.filter(recommendation=self.recommendation).exists())

    def test_other_organization_cannot_submit_response(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("respond_recommendation", args=[self.recommendation.pk]))
        self.assertEqual(response.status_code, 403)

    def test_auditor_can_review_response(self):
        response_record = Response.objects.create(
            recommendation=self.recommendation,
            version=1,
            declared_status=Response.DeclaredStatus.IN_PROGRESS,
            action_description="Acciones iniciales.",
            responsible_name="Responsable",
            responsible_job_title="Director",
            accuracy_declaration=True,
            submitted_by=self.institution_user,
        )
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("review_response", args=[response_record.pk]),
            {"outcome": Review.Outcome.CORRECTION_REQUIRED, "comments": "Adjunte el acta completa."},
        )
        self.assertRedirects(response, reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(response_record.review.outcome, Review.Outcome.CORRECTION_REQUIRED)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.CORRECTION_REQUIRED)

    def test_invalid_file_signature_is_rejected(self):
        upload = SimpleUploadedFile("documento.pdf", b"esto no es un pdf")
        with self.assertRaisesMessage(ValidationError, "no corresponde a un archivo PDF"):
            validate_evidence_file(upload)

    def test_unassigned_auditor_cannot_open_case(self):
        other_auditor = User.objects.create_user(
            username="otro-auditor",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.client.force_login(other_auditor)
        response = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(response.status_code, 404)

    def test_response_receipt_is_a_pdf(self):
        response_record = Response.objects.create(
            recommendation=self.recommendation,
            version=1,
            declared_status=Response.DeclaredStatus.IN_PROGRESS,
            action_description="Se inició la actualización de los registros.",
            responsible_name="Responsable",
            responsible_job_title="Director",
            accuracy_declaration=True,
            submitted_by=self.institution_user,
        )
        self.client.force_login(self.institution_user)
        result = self.client.get(reverse("response_receipt", args=[response_record.pk]))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Content-Type"], "application/pdf")
        content = b"".join(result.streaming_content)
        self.assertTrue(content.startswith(b"%PDF-"))

    def test_auditor_can_build_and_director_can_approve_publication(self):
        self.client.force_login(self.auditor)
        create_response = self.client.post(
            reverse("case_create"),
            {
                "reference": "IA-NEW-001",
                "title": "Examen especial de prueba",
                "audited_organization": self.center.pk,
                "report_date": date.today().isoformat(),
                "response_deadline": date.today().isoformat(),
                "assigned_auditor": self.other_user.pk,
            },
        )
        created_case = AuditCase.objects.get(reference="IA-NEW-001")
        self.assertRedirects(create_response, reverse("case_builder", args=[created_case.pk]))
        self.assertEqual(created_case.status, AuditCase.Status.DRAFT)
        self.assertEqual(created_case.assigned_auditor, self.auditor)
        self.assertEqual(created_case.created_by, self.auditor)
        report_document = AuditDocument.objects.create(
            case=created_case,
            organization=self.center,
            document_type=AuditDocument.DocumentType.REPORT,
            reference="BI-NEW-001",
            title="Informe de prueba",
            document_date=date.today(),
            version=1,
            status=AuditDocument.Status.DRAFT,
            visibility=AuditDocument.Visibility.AUDIT_ONLY,
            file=SimpleUploadedFile("informe.docx", b"documento de prueba"),
            original_filename="informe.docx",
            size=19,
            sha256="0" * 64,
            uploaded_by=self.auditor,
        )

        finding_response = self.client.post(
            reverse("finding_create", args=[created_case.pk]),
            {
                "number": 1,
                "title": "Falta de conciliaciones",
                "risk_level": Finding.RiskLevel.HIGH,
                "condition": "No se prepararon conciliaciones mensuales.",
            },
        )
        self.assertRedirects(finding_response, reverse("case_builder", args=[created_case.pk]))
        created_finding = created_case.findings.get(number=1)

        recommendation_response = self.client.post(
            reverse("recommendation_create", args=[created_finding.pk]),
            {
                "number": 1,
                "text": "Prepare y apruebe las conciliaciones mensualmente.",
                "responsible_organization": self.center.pk,
                "deadline": date.today().isoformat(),
                "evidence_requirements": "Conciliaciones firmadas.",
            },
        )
        self.assertRedirects(
            recommendation_response,
            reverse("case_builder", args=[created_case.pk]),
        )

        publish_response = self.client.post(reverse("case_publish", args=[created_case.pk]))
        self.assertRedirects(publish_response, reverse("case_detail", args=[created_case.pk]))
        created_case.refresh_from_db()
        self.assertEqual(created_case.status, AuditCase.Status.PENDING_PUBLICATION)
        decision = CaseDecision.objects.get(case=created_case, kind=CaseDecision.Kind.PUBLICATION)
        self.assertEqual(decision.document, report_document)
        self.assertTrue(
            ActivityLog.objects.filter(
                case=created_case, action="case_publication_requested"
            ).exists()
        )

        self.client.force_login(self.institution_user)
        hidden_response = self.client.get(reverse("case_detail", args=[created_case.pk]))
        self.assertEqual(hidden_response.status_code, 404)

        self.client.force_login(self.director)
        approval_response = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]),
            {
                "action": "approve",
                "justification": "El expediente reúne los requisitos técnicos para su publicación.",
            },
        )
        self.assertRedirects(approval_response, reverse("director_decisions"))
        created_case.refresh_from_db()
        decision.refresh_from_db()
        self.assertEqual(created_case.status, AuditCase.Status.PUBLISHED)
        self.assertEqual(decision.status, CaseDecision.Status.APPROVED)
        self.assertEqual(decision.decided_by, self.director)
        report_document.refresh_from_db()
        self.assertEqual(report_document.status, AuditDocument.Status.APPROVED)
        self.assertEqual(report_document.visibility, AuditDocument.Visibility.INSTITUTION)

        self.client.force_login(self.institution_user)
        visible_response = self.client.get(reverse("case_detail", args=[created_case.pk]))
        self.assertEqual(visible_response.status_code, 200)

    def test_institution_cannot_create_or_view_draft_cases(self):
        draft_case = AuditCase.objects.create(
            reference="IA-DRAFT-001",
            title="Borrador reservado",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.institution_user)
        create_response = self.client.get(reverse("case_create"))
        detail_response = self.client.get(reverse("case_detail", args=[draft_case.pk]))
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 404)

    def test_institution_cannot_respond_to_a_draft_recommendation_directly(self):
        draft_case = AuditCase.objects.create(
            reference="IA-DRAFT-DIRECT",
            title="Borrador con recomendación",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        draft_finding = Finding.objects.create(
            case=draft_case,
            number=1,
            title="Hallazgo aún no publicado",
            risk_level=Finding.RiskLevel.MEDIUM,
        )
        draft_recommendation = Recommendation.objects.create(
            finding=draft_finding,
            number=1,
            text="Recomendación reservada.",
            responsible_organization=self.center,
            deadline=date.today(),
        )
        self.client.force_login(self.institution_user)
        result = self.client.get(reverse("respond_recommendation", args=[draft_recommendation.pk]))
        self.assertEqual(result.status_code, 404)

    def test_case_cannot_be_published_until_required_content_is_complete(self):
        draft_case = AuditCase.objects.create(
            reference="IA-DRAFT-002",
            title="Borrador incompleto",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.auditor)
        result = self.client.post(reverse("case_publish", args=[draft_case.pk]))
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "Cargue el informe elaborado en Word")
        draft_case.refresh_from_db()
        self.assertEqual(draft_case.status, AuditCase.Status.DRAFT)

    def test_unassigned_auditor_cannot_edit_a_draft(self):
        other_auditor = User.objects.create_user(
            username="auditor-sin-asignacion",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        draft_case = AuditCase.objects.create(
            reference="IA-DRAFT-003",
            title="Borrador asignado",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(other_auditor)
        result = self.client.get(reverse("case_builder", args=[draft_case.pk]))
        self.assertEqual(result.status_code, 403)

    def test_director_dashboard_is_restricted_to_director(self):
        self.client.force_login(self.director)
        result = self.client.get(reverse("director_dashboard"))
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "Inicio")

        self.client.force_login(self.auditor)
        forbidden = self.client.get(reverse("director_dashboard"))
        self.assertEqual(forbidden.status_code, 403)

        self.client.force_login(self.technical_admin)
        forbidden = self.client.get(reverse("director_dashboard"))
        self.assertEqual(forbidden.status_code, 403)

    def test_auditor_dashboard_statistics_only_include_assigned_cases(self):
        other_auditor = User.objects.create_user(
            username="auditor-otro",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        other_case = AuditCase.objects.create(
            reference="IA-FUERA-SCOPE",
            title="Expediente fuera del alcance",
            audited_organization=self.other_center,
            status=AuditCase.Status.UNDER_REVIEW,
            assigned_auditor=other_auditor,
            created_by=other_auditor,
        )
        other_finding = Finding.objects.create(
            case=other_case,
            number=1,
            title="Hallazgo crítico fuera del alcance",
            risk_level=Finding.RiskLevel.CRITICAL,
        )
        Recommendation.objects.create(
            finding=other_finding,
            number=1,
            text="Recomendación fuera del alcance.",
            responsible_organization=self.other_center,
            deadline=date.today() - timedelta(days=10),
        )

        self.client.force_login(self.auditor)
        result = self.client.get(reverse("dashboard"))

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context["total_cases"], 1)
        self.assertEqual(result.context["total_recommendations"], 1)
        self.assertEqual(result.context["critical_findings"], 0)
        self.assertEqual(result.context["overdue_recommendations"], 0)
        self.assertNotContains(result, "IA-FUERA-SCOPE")

    def test_auditor_dashboard_uses_extended_deadline_for_alerts(self):
        self.recommendation.deadline = date.today() - timedelta(days=2)
        self.recommendation.save(update_fields=["deadline"])
        DeadlineExtension.objects.create(
            recommendation=self.recommendation,
            previous_deadline=self.recommendation.deadline,
            business_days=5,
            new_deadline=date.today() + timedelta(days=5),
            reason="Prórroga válida para completar las evidencias requeridas.",
            granted_by=self.auditor,
        )

        self.client.force_login(self.auditor)
        result = self.client.get(reverse("dashboard"))

        self.assertEqual(result.context["overdue_recommendations"], 0)
        self.assertEqual(result.context["due_soon_recommendations"], 1)

    def test_director_statistics_are_restricted_and_filter_by_auditor(self):
        other_auditor = User.objects.create_user(
            username="auditor-estadisticas",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        AuditCase.objects.create(
            reference="IA-STATS-002",
            title="Segundo expediente estadístico",
            audited_organization=self.other_center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=other_auditor,
            created_by=other_auditor,
        )

        self.client.force_login(self.director)
        result = self.client.get(
            reverse("director_statistics"),
            {"period": "all", "auditor": self.auditor.pk},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context["total_cases"], 1)
        self.assertEqual(result.context["selected_auditor"], self.auditor)
        self.assertContains(result, "Análisis de centros educativos")

        self.client.force_login(self.auditor)
        forbidden = self.client.get(reverse("director_statistics"))
        self.assertEqual(forbidden.status_code, 403)

    def test_director_can_download_complete_statistics_xlsx(self):
        self.case.title = "=HYPERLINK(\"https://example.invalid\",\"texto\")"
        self.case.save(update_fields=["title"])

        self.client.force_login(self.director)
        result = self.client.get(
            reverse("director_statistics_xlsx"),
            {"period": "all", "auditor": self.auditor.pk},
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn(".xlsx", result["Content-Disposition"])
        self.assertEqual(result["Cache-Control"], "private, no-store")
        content = b"".join(result.streaming_content)
        workbook = load_workbook(BytesIO(content), data_only=False)

        self.assertEqual(
            workbook.sheetnames,
            [
                "Resumen",
                "Expedientes",
                "Hallazgos",
                "Recomendaciones",
                "Respuestas y revisiones",
                "Prórrogas",
                "Auditores",
                "Instituciones",
                "Dependencias responsables",
                "Series mensuales",
                "Alertas y calidad",
                "Controles",
                "Metodología",
            ],
        )
        self.assertEqual(
            workbook["Resumen"]["A1"].value,
            "Informe estadístico y analítico de Auditoría Interna",
        )
        self.assertEqual(workbook["Resumen"]["D13"].value, "N/D")
        self.assertGreaterEqual(len(workbook["Resumen"]._charts), 3)
        self.assertEqual(workbook["Expedientes"]["A5"].value, self.case.reference)
        self.assertTrue(workbook["Expedientes"]["B5"].value.startswith("'="))
        self.assertEqual(workbook["Expedientes"]["B5"].data_type, "s")
        self.assertEqual(workbook["Recomendaciones"]["A5"].value, self.case.reference)
        self.assertIsNone(workbook["Auditores"]["N5"].value)
        self.assertIsNone(workbook["Instituciones"]["O5"].value)
        self.assertTrue(
            all(
                workbook["Controles"].cell(row=row, column=4).value == "OK"
                for row in range(5, workbook["Controles"].max_row + 1)
            )
        )

        log = ActivityLog.objects.get(action="director_statistics_xlsx_exported")
        self.assertEqual(log.actor, self.director)
        self.assertEqual(log.details["filters"]["auditor_id"], self.auditor.pk)
        self.assertEqual(log.details["rows"]["cases"], 1)
        self.assertEqual(log.details["sha256"], hashlib.sha256(content).hexdigest())

    def test_statistics_xlsx_uses_effective_deadline_and_responsible_dependency(self):
        original_deadline = date.today() - timedelta(days=2)
        new_deadline = date.today() + timedelta(days=3)
        self.recommendation.deadline = original_deadline
        self.recommendation.responsible_organization = self.other_center
        self.recommendation.save(
            update_fields=["deadline", "responsible_organization"]
        )
        DeadlineExtension.objects.create(
            recommendation=self.recommendation,
            previous_deadline=original_deadline,
            business_days=4,
            new_deadline=new_deadline,
            reason="Prórroga de prueba para completar la documentación.",
            granted_by=self.director,
        )

        self.client.force_login(self.director)
        result = self.client.get(
            reverse("director_statistics_xlsx"), {"period": "all"}
        )
        content = b"".join(result.streaming_content)
        workbook = load_workbook(BytesIO(content), data_only=False)

        recommendation_row = workbook["Recomendaciones"][5]
        self.assertEqual(recommendation_row[12].value.date(), original_deadline)
        self.assertEqual(recommendation_row[13].value.date(), new_deadline)
        self.assertEqual(recommendation_row[14].value, 0)
        self.assertEqual(recommendation_row[15].value, 3)
        self.assertEqual(recommendation_row[17].value, 1)
        responsible_codes = {
            workbook["Dependencias responsables"].cell(row=row, column=1).value
            for row in range(5, workbook["Dependencias responsables"].max_row + 1)
        }
        self.assertIn(self.other_center.code, responsible_codes)

    def test_statistics_xlsx_rejects_invalid_filters_without_logging(self):
        self.client.force_login(self.director)
        result = self.client.get(
            reverse("director_statistics_xlsx"),
            {"period": "custom", "start": "2026-08-20", "end": "2026-08-10"},
        )

        self.assertEqual(result.status_code, 400)
        self.assertContains(
            result,
            "La fecha inicial no puede ser posterior a la fecha final.",
            status_code=400,
        )
        self.assertFalse(
            ActivityLog.objects.filter(
                action="director_statistics_xlsx_exported"
            ).exists()
        )

    def test_statistics_xlsx_is_exclusive_to_director(self):
        for user in (self.auditor, self.technical_admin, self.institution_user):
            self.client.force_login(user)
            result = self.client.get(reverse("director_statistics_xlsx"))
            self.assertEqual(result.status_code, 403)

        self.client.logout()
        anonymous = self.client.get(reverse("director_statistics_xlsx"))
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/ingresar/", anonymous.url)

    def test_director_can_return_publication_with_justification(self):
        draft_case = AuditCase.objects.create(
            reference="IA-RETURN-001",
            title="Borrador para devolución",
            audited_organization=self.center,
            report_file=SimpleUploadedFile(
                "informe.pdf", b"%PDF-1.4\ncontenido", content_type="application/pdf"
            ),
            report_date=date.today(),
            response_deadline=date.today(),
            status=AuditCase.Status.PENDING_PUBLICATION,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        decision = CaseDecision.objects.create(
            case=draft_case,
            kind=CaseDecision.Kind.PUBLICATION,
            requested_by=self.auditor,
            previous_case_status=AuditCase.Status.DRAFT,
        )
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]),
            {
                "action": "return",
                "justification": "Debe corregirse la identificación oficial del informe presentado.",
            },
        )
        self.assertRedirects(result, reverse("director_decisions"))
        draft_case.refresh_from_db()
        decision.refresh_from_db()
        self.assertEqual(draft_case.status, AuditCase.Status.DRAFT)
        self.assertEqual(decision.status, CaseDecision.Status.RETURNED)
        self.assertTrue(
            ActivityLog.objects.filter(
                case=draft_case, action="case_publication_returned"
            ).exists()
        )

    def test_director_decision_requires_justification(self):
        self.case.status = AuditCase.Status.PENDING_PUBLICATION
        self.case.save(update_fields=["status"])
        decision = CaseDecision.objects.create(
            case=self.case,
            kind=CaseDecision.Kind.PUBLICATION,
            requested_by=self.auditor,
            previous_case_status=AuditCase.Status.DRAFT,
        )
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]),
            {"action": "approve", "justification": "corto"},
        )
        self.assertEqual(result.status_code, 200)
        decision.refresh_from_db()
        self.case.refresh_from_db()
        self.assertEqual(decision.status, CaseDecision.Status.PENDING)
        self.assertEqual(self.case.status, AuditCase.Status.PENDING_PUBLICATION)

    def test_auditor_and_technical_admin_cannot_resolve_director_decision(self):
        self.case.status = AuditCase.Status.PENDING_PUBLICATION
        self.case.save(update_fields=["status"])
        decision = CaseDecision.objects.create(
            case=self.case,
            kind=CaseDecision.Kind.PUBLICATION,
            requested_by=self.auditor,
            previous_case_status=AuditCase.Status.DRAFT,
        )
        payload = {
            "action": "approve",
            "justification": "Intento de aprobación sin autoridad directiva suficiente.",
        }
        self.client.force_login(self.auditor)
        auditor_result = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]), payload
        )
        self.assertEqual(auditor_result.status_code, 403)

        self.client.force_login(self.technical_admin)
        technical_result = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]), payload
        )
        self.assertEqual(technical_result.status_code, 403)
        decision.refresh_from_db()
        self.assertEqual(decision.status, CaseDecision.Status.PENDING)

    def test_director_can_approve_case_closure(self):
        self.recommendation.status = Recommendation.Status.COMPLIED
        self.recommendation.save(update_fields=["status"])
        self.case.status = AuditCase.Status.UNDER_REVIEW
        self.case.save(update_fields=["status"])

        self.client.force_login(self.auditor)
        request_result = self.client.post(
            reverse("request_case_closure", args=[self.case.pk]),
            {
                "justification": (
                    "Todas las recomendaciones cuentan con un resultado definitivo documentado."
                )
            },
        )
        self.assertRedirects(request_result, reverse("case_detail", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, AuditCase.Status.PENDING_CLOSURE)
        decision = CaseDecision.objects.get(case=self.case, kind=CaseDecision.Kind.CLOSURE)

        self.client.force_login(self.director)
        approval_result = self.client.post(
            reverse("director_decision_detail", args=[decision.pk]),
            {
                "action": "approve",
                "justification": "Se verificó el resultado final y la trazabilidad del expediente.",
            },
        )
        self.assertRedirects(approval_result, reverse("director_decisions"))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, AuditCase.Status.CLOSED)

    def test_closure_request_is_blocked_with_open_recommendations(self):
        self.client.force_login(self.auditor)
        result = self.client.post(
            reverse("request_case_closure", args=[self.case.pk]),
            {
                "justification": (
                    "Se solicita el cierre aunque todavía existe trabajo pendiente de revisión."
                )
            },
        )
        self.assertEqual(result.status_code, 200)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, AuditCase.Status.PUBLISHED)
        self.assertFalse(
            CaseDecision.objects.filter(case=self.case, kind=CaseDecision.Kind.CLOSURE).exists()
        )

    def test_director_can_reassign_case_with_audit_log(self):
        replacement = User.objects.create_user(
            username="auditor-reemplazo",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.client.force_login(self.director)
        result = self.client.post(
            reverse("director_reassign_case", args=[self.case.pk]),
            {
                "assigned_auditor": replacement.pk,
                "justification": "Se redistribuye la carga por disponibilidad operativa del equipo.",
            },
        )
        self.assertRedirects(result, reverse("case_detail", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertEqual(self.case.assigned_auditor, replacement)
        log = ActivityLog.objects.get(case=self.case, action="case_reassigned")
        self.assertEqual(log.details["previous_auditor_id"], self.auditor.pk)
        self.assertEqual(log.details["new_auditor_id"], replacement.pk)

    def test_director_cannot_create_case_or_edit_auditor_draft(self):
        draft_case = AuditCase.objects.create(
            reference="IA-DIRECTOR-DRAFT",
            title="Borrador del auditor",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.director)
        create_result = self.client.get(reverse("case_create"))
        edit_result = self.client.get(reverse("case_builder", args=[draft_case.pk]))
        self.assertEqual(create_result.status_code, 403)
        self.assertEqual(edit_result.status_code, 403)

    def test_historical_recommendations_are_imported_once(self):
        historical_document = AuditDocument.objects.create(
            organization=self.center,
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
            reference="IA-HIST-001",
            title="Informe histórico",
            document_date=date(2025, 1, 15),
            version=1,
            status=AuditDocument.Status.HISTORICAL,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("historico.pdf", b"%PDF-1.4\nhistorico"),
            original_filename="historico.pdf",
            size=20,
            sha256="1" * 64,
            uploaded_by=self.auditor,
        )
        historical_recommendation = HistoricalRecommendation.objects.create(
            source_document=historical_document,
            number="5",
            text="Complete la liquidación pendiente.",
            responsible_organization=self.center,
            status=HistoricalRecommendation.Status.NOT_COMPLIED,
            comments="No se recibió documentación suficiente.",
            recorded_by=self.auditor,
        )
        draft_case = AuditCase.objects.create(
            reference="IA-FOLLOW-UP",
            title="Seguimiento histórico",
            audited_organization=self.center,
            response_deadline=date.today() + timedelta(days=10),
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.auditor)
        result = self.client.post(
            reverse("case_import_recommendations", args=[draft_case.pk]),
            {"recommendations": [historical_recommendation.pk]},
        )
        self.assertRedirects(result, reverse("case_builder", args=[draft_case.pk]))
        imported = Recommendation.objects.get(
            finding__case=draft_case,
            source_recommendation=historical_recommendation,
        )
        self.assertEqual(imported.text, historical_recommendation.text)
        self.assertEqual(imported.status, Recommendation.Status.PENDING)
        self.assertEqual(imported.deadline, draft_case.response_deadline)

        duplicate_attempt = self.client.post(
            reverse("case_import_recommendations", args=[draft_case.pk]),
            {"recommendations": [historical_recommendation.pk]},
        )
        self.assertEqual(duplicate_attempt.status_code, 200)
        self.assertEqual(
            Recommendation.objects.filter(
                finding__case=draft_case,
                source_recommendation=historical_recommendation,
            ).count(),
            1,
        )

    def test_report_repository_combines_report_types_without_type_filter(self):
        current_document = AuditDocument.objects.create(
            case=self.case,
            organization=self.center,
            document_type=AuditDocument.DocumentType.REPORT,
            reference="IA-ACTUAL-001",
            title="Informe del expediente actual",
            document_date=date.today(),
            version=2,
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("actual.docx", b"documento actual"),
            original_filename="actual.docx",
            size=16,
            sha256="4" * 64,
            uploaded_by=self.auditor,
        )
        previous_document = AuditDocument.objects.create(
            organization=self.center,
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
            reference="IA-ANTERIOR-001",
            title="Informe anterior registrado",
            document_date=date.today() - timedelta(days=365),
            version=1,
            status=AuditDocument.Status.HISTORICAL,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("anterior.pdf", b"%PDF-1.4\nanterior"),
            original_filename="anterior.pdf",
            size=18,
            sha256="5" * 64,
            uploaded_by=self.auditor,
        )
        HistoricalRecommendation.objects.create(
            source_document=previous_document,
            number="R-1",
            text="Complete el control pendiente.",
            responsible_organization=self.center,
            status=HistoricalRecommendation.Status.PARTIAL,
            recorded_by=self.auditor,
        )
        self.client.force_login(self.director)

        combined = self.client.get(reverse("historical_document_list"))
        self.assertContains(combined, current_document.reference)
        self.assertContains(combined, previous_document.reference)
        self.assertContains(combined, "Informe del expediente")
        self.assertContains(combined, "Informe anterior")
        self.assertNotContains(combined, 'name="type"')

        legacy_type_parameter = self.client.get(
            reverse("historical_document_list"),
            {"type": AuditDocument.DocumentType.REPORT},
        )
        self.assertContains(legacy_type_parameter, current_document.reference)
        self.assertContains(legacy_type_parameter, previous_document.reference)

    def test_report_repository_filters_by_correlated_department_and_district(self):
        self.center.department = "Departamento A"
        self.center.district = "Distrito A1"
        self.center.save(update_fields=["department", "district"])
        self.other_center.department = "Departamento B"
        self.other_center.district = "Distrito B1"
        self.other_center.save(update_fields=["department", "district"])
        included = AuditDocument.objects.create(
            organization=self.center,
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
            reference="IA-UBICACION-A",
            title="Informe del departamento A",
            status=AuditDocument.Status.HISTORICAL,
            file=SimpleUploadedFile("ubicacion-a.pdf", b"%PDF-1.4\na"),
            original_filename="ubicacion-a.pdf",
            size=11,
            sha256="a" * 64,
            uploaded_by=self.auditor,
        )
        excluded = AuditDocument.objects.create(
            organization=self.other_center,
            document_type=AuditDocument.DocumentType.HISTORICAL_REPORT,
            reference="IA-UBICACION-B",
            title="Informe del departamento B",
            status=AuditDocument.Status.HISTORICAL,
            file=SimpleUploadedFile("ubicacion-b.pdf", b"%PDF-1.4\nb"),
            original_filename="ubicacion-b.pdf",
            size=11,
            sha256="b" * 64,
            uploaded_by=self.auditor,
        )
        self.client.force_login(self.director)

        result = self.client.get(
            reverse("historical_document_list"),
            {"department": "Departamento A", "district": "Distrito A1"},
        )

        self.assertEqual(list(result.context["district_options"]), ["Distrito A1"])
        self.assertContains(result, included.reference)
        self.assertNotContains(result, excluded.reference)
        self.assertNotContains(result, "Distrito B1")

    def test_report_repository_hides_unassigned_case_reports_from_auditor(self):
        assigned_document = AuditDocument.objects.create(
            case=self.case,
            organization=self.center,
            document_type=AuditDocument.DocumentType.REPORT,
            reference="IA-ASIGNADO-001",
            title="Informe asignado",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("asignado.docx", b"asignado"),
            original_filename="asignado.docx",
            size=8,
            sha256="6" * 64,
            uploaded_by=self.auditor,
        )
        other_auditor = User.objects.create_user(
            username="auditor-repositorio",
            password="UnaClaveDePrueba!2026",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )
        other_case = AuditCase.objects.create(
            reference="IA-OTRO-001",
            title="Expediente de otro auditor",
            audited_organization=self.other_center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=other_auditor,
            created_by=other_auditor,
        )
        hidden_document = AuditDocument.objects.create(
            case=other_case,
            organization=self.other_center,
            document_type=AuditDocument.DocumentType.REPORT,
            reference="IA-NO-ASIGNADO-001",
            title="Informe no asignado",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("no-asignado.docx", b"no asignado"),
            original_filename="no-asignado.docx",
            size=11,
            sha256="7" * 64,
            uploaded_by=other_auditor,
        )
        self.client.force_login(self.auditor)

        result = self.client.get(reverse("historical_document_list"))

        self.assertContains(result, assigned_document.reference)
        self.assertNotContains(result, hidden_document.reference)
        self.assertEqual(
            list(result.context["organizations"]),
            [self.center],
        )

    def test_auditor_can_upload_versioned_word_report(self):
        draft_case = AuditCase.objects.create(
            reference="IA-WORD-001",
            title="Informe elaborado externamente",
            audited_organization=self.center,
            report_date=date.today(),
            response_deadline=date.today() + timedelta(days=5),
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.auditor)

        first_upload = self.client.post(
            reverse("case_report_upload", args=[draft_case.pk]),
            {
                "reference": "BI-WORD-001",
                "title": "Borrador de informe",
                "document_date": (date.today() + timedelta(days=1)).isoformat(),
                "file": make_docx_upload("borrador-v1.docx"),
            },
        )
        second_upload = self.client.post(
            reverse("case_report_upload", args=[draft_case.pk]),
            {
                "reference": "BI-WORD-001",
                "title": "Borrador corregido",
                "document_date": date.today().isoformat(),
                "file": make_docx_upload("borrador-v2.docx"),
            },
        )

        self.assertRedirects(first_upload, reverse("case_builder", args=[draft_case.pk]))
        self.assertRedirects(second_upload, reverse("case_builder", args=[draft_case.pk]))
        self.assertEqual(draft_case.documents.count(), 2)
        self.assertEqual(
            list(draft_case.documents.order_by("version").values_list("version", flat=True)),
            [1, 2],
        )
        self.assertTrue(
            draft_case.documents.exclude(sha256="").filter(size__gt=0).count(),
        )

        finding = Finding.objects.create(
            case=draft_case,
            number=1,
            title="Seguimiento requerido",
            risk_level=Finding.RiskLevel.HIGH,
        )
        Recommendation.objects.create(
            finding=finding,
            number=1,
            text="Presente la documentación de seguimiento.",
            responsible_organization=self.center,
            deadline=draft_case.response_deadline,
        )
        publication = self.client.post(reverse("case_publish", args=[draft_case.pk]))
        self.assertRedirects(publication, reverse("case_detail", args=[draft_case.pk]))
        decision = CaseDecision.objects.get(
            case=draft_case,
            kind=CaseDecision.Kind.PUBLICATION,
        )
        self.assertEqual(decision.document.version, 2)

    def test_case_report_rejects_pdf_even_when_it_is_valid(self):
        draft_case = AuditCase.objects.create(
            reference="IA-WORD-ONLY",
            title="Informe que debe permanecer en Word",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.auditor)

        response = self.client.post(
            reverse("case_report_upload", args=[draft_case.pk]),
            {
                "reference": "BI-WORD-ONLY",
                "title": "Informe incorrecto",
                "document_date": date.today().isoformat(),
                "file": SimpleUploadedFile(
                    "informe.pdf",
                    b"%PDF-1.4\ncontenido",
                    content_type="application/pdf",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "formato Word (.docx)")
        self.assertFalse(draft_case.documents.exists())

    def test_business_day_extension_skips_weekend_and_holiday(self):
        BusinessDayHoliday.objects.create(
            date=date(2026, 8, 17),
            name="Asueto de prueba",
        )
        self.assertEqual(
            add_business_days(date(2026, 8, 14), 1),
            date(2026, 8, 18),
        )

    def test_extension_view_records_new_business_day_deadline(self):
        BusinessDayHoliday.objects.create(
            date=date(2026, 8, 17),
            name="Asueto de prueba",
        )
        self.recommendation.deadline = date(2026, 8, 14)
        self.recommendation.save(update_fields=["deadline"])
        self.client.force_login(self.auditor)

        response = self.client.post(
            reverse("grant_deadline_extension", args=[self.recommendation.pk]),
            {
                "business_days": 1,
                "reason": "Se concede tiempo para completar la documentación requerida.",
            },
        )

        self.assertRedirects(response, reverse("case_detail", args=[self.case.pk]))
        self.recommendation.refresh_from_db()
        extension = self.recommendation.deadline_extensions.get()
        self.assertEqual(extension.previous_deadline, date(2026, 8, 14))
        self.assertEqual(extension.new_deadline, date(2026, 8, 18))
        self.assertEqual(self.recommendation.deadline, date(2026, 8, 18))

    def test_overdue_recommendation_without_response_is_marked_not_complied(self):
        self.recommendation.deadline = date.today() - timedelta(days=1)
        self.recommendation.save(update_fields=["deadline"])

        count = mark_overdue_recommendations(today=date.today())

        self.assertEqual(count, 1)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.NOT_COMPLIED)
        self.assertIsNotNone(self.recommendation.no_response_recorded_at)
        self.assertTrue(
            ActivityLog.objects.filter(
                case=self.case,
                action="recommendation_no_response",
                target_id=str(self.recommendation.pk),
            ).exists()
        )

    def test_submitted_response_is_not_marked_overdue(self):
        self.recommendation.deadline = date.today() - timedelta(days=1)
        self.recommendation.status = Recommendation.Status.SUBMITTED
        self.recommendation.save(update_fields=["deadline", "status"])

        count = mark_overdue_recommendations(today=date.today())

        self.assertEqual(count, 0)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.SUBMITTED)

    def test_draft_recommendation_is_not_marked_overdue(self):
        self.case.status = AuditCase.Status.DRAFT
        self.case.save(update_fields=["status"])
        self.recommendation.deadline = date.today() - timedelta(days=1)
        self.recommendation.save(update_fields=["deadline"])

        count = mark_overdue_recommendations(today=date.today())

        self.assertEqual(count, 0)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.PENDING)

    def test_latest_extension_prevents_premature_overdue_status(self):
        self.recommendation.deadline = date.today() - timedelta(days=2)
        self.recommendation.save(update_fields=["deadline"])
        DeadlineExtension.objects.create(
            recommendation=self.recommendation,
            previous_deadline=self.recommendation.deadline,
            business_days=5,
            new_deadline=date.today() + timedelta(days=3),
            reason="Prórroga de prueba todavía vigente.",
            granted_by=self.auditor,
        )

        count = mark_overdue_recommendations(today=date.today())

        self.assertEqual(count, 0)
        self.recommendation.refresh_from_db()
        self.assertEqual(self.recommendation.status, Recommendation.Status.PENDING)

    def test_center_cannot_view_another_units_response_or_evidence(self):
        other_recommendation = Recommendation.objects.create(
            finding=self.finding,
            number=2,
            text="Remita el expediente disciplinario.",
            responsible_organization=self.other_center,
            deadline=date.today(),
            status=Recommendation.Status.SUBMITTED,
        )
        response_record = Response.objects.create(
            recommendation=other_recommendation,
            version=1,
            declared_status=Response.DeclaredStatus.COMPLETED,
            action_description="Contenido reservado de otra dependencia.",
            responsible_name="Responsable Dos",
            responsible_job_title="Jefatura",
            accuracy_declaration=True,
            submitted_by=self.other_user,
        )
        evidence = Evidence.objects.create(
            response=response_record,
            file=SimpleUploadedFile("reservado.pdf", b"%PDF-1.4\nreservado"),
            original_filename="reservado.pdf",
            category=Evidence.Category.OTHER,
            description="Documento reservado",
            size=20,
            sha256="2" * 64,
            scan_status=Evidence.ScanStatus.CLEAN,
            uploaded_by=self.other_user,
        )
        self.client.force_login(self.institution_user)

        detail = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Contenido reservado de otra dependencia")
        download = self.client.get(reverse("download_evidence", args=[evidence.pk]))
        self.assertEqual(download.status_code, 403)

    def test_institution_history_shows_approved_documents(self):
        document = AuditDocument.objects.create(
            case=self.case,
            organization=self.center,
            document_type=AuditDocument.DocumentType.REPORT,
            reference="IA-001-APROBADO",
            title="Informe aprobado",
            document_date=date.today(),
            version=1,
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            file=SimpleUploadedFile("aprobado.docx", b"documento"),
            original_filename="aprobado.docx",
            size=9,
            sha256="3" * 64,
            uploaded_by=self.auditor,
        )
        self.client.force_login(self.institution_user)

        history = self.client.get(reverse("institution_history"))

        self.assertContains(history, document.reference)
        self.assertContains(history, "Informe aprobado")

    def test_institution_history_includes_visible_historical_recommendations(self):
        self.client.force_login(self.auditor)
        upload = self.client.post(
            reverse("historical_document_create"),
            {
                "organization": self.center.pk,
                "reference": "HIST-CENTRO-1",
                "visibility": AuditDocument.Visibility.INSTITUTION,
                "attachments-TOTAL_FORMS": "0",
                "attachments-INITIAL_FORMS": "0",
                "title": "Informe histórico del centro",
                "document_date": date(2025, 6, 1).isoformat(),
                "file": SimpleUploadedFile(
                    "historico.pdf",
                    b"%PDF-1.4\ncontenido historico",
                    content_type="application/pdf",
                ),
            },
        )
        historical_document = AuditDocument.objects.get(reference="HIST-CENTRO-1")
        self.assertRedirects(
            upload,
            reverse("historical_document_detail", args=[historical_document.pk]),
        )
        self.assertEqual(
            historical_document.visibility,
            AuditDocument.Visibility.INSTITUTION,
        )
        historical_recommendation = HistoricalRecommendation.objects.create(
            source_document=historical_document,
            number="R-7",
            text="Complete el registro de bienes pendientes.",
            responsible_organization=self.center,
            status=HistoricalRecommendation.Status.PARTIAL,
            comments="Se encontró documentación incompleta.",
            recorded_by=self.auditor,
        )

        self.client.force_login(self.institution_user)
        history = self.client.get(reverse("institution_history"))

        self.assertContains(history, historical_recommendation.text)
        self.assertContains(history, historical_recommendation.comments)
        self.assertContains(
            history,
            reverse("historical_document_detail", args=[historical_document.pk]),
        )
