import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization

from .models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    Evidence,
    Finding,
    Recommendation,
    Response,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="auditoria-equipo-")


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, FILE_SCAN_REQUIRED=False)
class TeamReadOnlyAccessTests(TestCase):
    """El equipo auditor consulta expedientes publicados ajenos sin poder actuar sobre ellos."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        audit_unit = Organization.objects.create(
            code="DAI-EQ", name="Auditoría Interna", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.center = Organization.objects.create(
            code="10754", name="Centro Uno", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.other_center = Organization.objects.create(
            code="10755", name="Centro Dos", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.owner = User.objects.create_user(
            username="auditora-titular", first_name="Ana", last_name="Titular",
            role=User.Role.AUDITOR, organization=audit_unit, must_change_password=False,
        )
        self.teammate = User.objects.create_user(
            username="auditor-equipo", role=User.Role.AUDITOR, organization=audit_unit,
            must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="directora-equipo", role=User.Role.AUDIT_MANAGER, organization=audit_unit,
            must_change_password=False,
        )
        self.institution = User.objects.create_user(
            username="10755", role=User.Role.INSTITUTION, organization=self.other_center,
            must_change_password=False,
        )
        self.case = self.make_case("IA-EQ-001", AuditCase.Status.UNDER_REVIEW)
        finding = Finding.objects.create(
            case=self.case, number=1, title="Caja sin arqueos", risk_level=Finding.RiskLevel.HIGH
        )
        self.recommendation = Recommendation.objects.create(
            finding=finding, number=1, text="Realice arqueos.", responsible_organization=self.center,
            deadline=date(2099, 1, 1), status=Recommendation.Status.SUBMITTED,
        )
        self.response = Response.objects.create(
            recommendation=self.recommendation, version=1,
            declared_status=Response.DeclaredStatus.COMPLETED, action_description="Se hicieron arqueos.",
            responsible_name="Directora", responsible_job_title="Dirección", accuracy_declaration=True,
            submitted_by=self.institution,
        )
        self.evidence = Evidence.objects.create(
            response=self.response,
            file=SimpleUploadedFile("acta.pdf", b"%PDF-1.4 prueba", content_type="application/pdf"),
            original_filename="acta.pdf", category=Evidence.Category.MINUTES, description="Actas",
            size=15, sha256="a" * 64, scan_status=Evidence.ScanStatus.CLEAN, uploaded_by=self.institution,
        )

    def make_case(self, reference, status, owner=None, center=None, **extra):
        owner = owner or self.owner
        return AuditCase.objects.create(
            reference=reference, title=f"Expediente {reference}", audited_organization=center or self.center,
            status=status, assigned_auditor=owner, created_by=owner, **extra,
        )

    def make_report(self, case, status, version):
        return AuditDocument.objects.create(
            case=case, organization=case.audited_organization,
            document_type=AuditDocument.DocumentType.REPORT, reference=f"INF-{version}",
            title=f"Informe versión {version}", document_date=date(2026, 1, 1), version=version,
            status=status, visibility=AuditDocument.Visibility.AUDIT_ONLY,
            file=SimpleUploadedFile(f"informe-{version}.docx", b"informe"),
            original_filename=f"informe-{version}.docx", size=7, sha256="b" * 64, uploaded_by=self.owner,
        )

    # ---------- Consulta ----------

    def test_teammate_opens_published_case_in_read_only_mode(self):
        self.client.force_login(self.teammate)
        page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Solo consulta")
        self.assertContains(page, "Ana Titular")
        self.assertNotContains(page, reverse("review_response", args=[self.response.pk]))
        self.assertNotContains(page, reverse("grant_deadline_extension", args=[self.recommendation.pk]))
        self.assertNotContains(page, reverse("request_case_closure", args=[self.case.pk]))
        self.assertContains(page, reverse("download_evidence", args=[self.evidence.pk]))
        log = ActivityLog.objects.get(action="case_viewed_by_team")
        self.assertEqual((log.actor, log.case), (self.teammate, self.case))

    def test_assigned_auditor_keeps_actions_and_is_not_logged_as_team_view(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertNotContains(page, "Solo consulta")
        self.assertContains(page, reverse("review_response", args=[self.response.pk]))
        self.assertFalse(ActivityLog.objects.filter(action="case_viewed_by_team").exists())

    def test_teammate_cannot_act_on_the_case(self):
        self.client.force_login(self.teammate)
        review = self.client.post(
            reverse("review_response", args=[self.response.pk]),
            {"outcome": "complied", "comments": "Intento ajeno."},
        )
        self.assertEqual(review.status_code, 404)
        self.assertFalse(hasattr(Response.objects.get(pk=self.response.pk), "review"))
        extension = self.client.post(reverse("grant_deadline_extension", args=[self.recommendation.pk]))
        self.assertEqual(extension.status_code, 403)
        closure = self.client.post(reverse("request_case_closure", args=[self.case.pk]))
        self.assertIn(closure.status_code, (403, 404))
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, AuditCase.Status.UNDER_REVIEW)

    def test_teammate_downloads_evidence_and_receipt_of_team_cases(self):
        self.client.force_login(self.teammate)
        self.assertEqual(self.client.get(reverse("download_evidence", args=[self.evidence.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("response_receipt", args=[self.response.pk])).status_code, 200)
        self.assertTrue(
            ActivityLog.objects.filter(action="evidence_downloaded", actor=self.teammate).exists()
        )

    def test_drafts_pending_and_reserved_cases_stay_private(self):
        draft = self.make_case("IA-EQ-BORRADOR", AuditCase.Status.DRAFT)
        pending = self.make_case("IA-EQ-PENDIENTE", AuditCase.Status.PENDING_PUBLICATION)
        AuditCase.objects.filter(pk=self.case.pk).update(is_reserved=True)
        self.client.force_login(self.teammate)
        for case in (draft, pending, self.case):
            with self.subTest(case=case.reference):
                self.assertEqual(self.client.get(reverse("case_detail", args=[case.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("download_evidence", args=[self.evidence.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("response_receipt", args=[self.response.pk])).status_code, 404)

    def test_teammate_only_sees_the_approved_report_version(self):
        approved = self.make_report(self.case, AuditDocument.Status.APPROVED, 1)
        returned = self.make_report(self.case, AuditDocument.Status.RETURNED, 2)
        self.client.force_login(self.teammate)
        page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertContains(page, "Informe versión 1")
        self.assertNotContains(page, "Informe versión 2")
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[approved.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[returned.pk])).status_code, 403)
        repository = self.client.get(reverse("historical_document_list"))
        self.assertContains(repository, "INF-1")
        self.assertNotContains(repository, "INF-2")

    def test_institution_scope_is_unchanged(self):
        self.client.force_login(self.institution)
        self.assertEqual(self.client.get(reverse("case_detail", args=[self.case.pk])).status_code, 404)

    # ---------- Listado ----------

    def test_case_list_keeps_my_portfolio_by_default_and_offers_the_team_scope(self):
        own = self.make_case("IA-PROPIO-001", AuditCase.Status.PUBLISHED, owner=self.teammate)
        other_draft = self.make_case("IA-EQ-BORRADOR", AuditCase.Status.DRAFT)
        reserved = self.make_case("IA-EQ-RESERVADO", AuditCase.Status.PUBLISHED, is_reserved=True)
        self.client.force_login(self.teammate)

        mine = self.client.get(reverse("case_list"))
        self.assertEqual([case.pk for case in mine.context["cases"]], [own.pk])
        self.assertContains(mine, "Todo el equipo")

        team = self.client.get(reverse("case_list"), {"alcance": "equipo"})
        references = {case.reference for case in team.context["cases"]}
        self.assertEqual(references, {"IA-PROPIO-001", "IA-EQ-001"})
        self.assertNotIn(other_draft.reference, references)
        self.assertNotIn(reserved.reference, references)
        self.assertContains(team, "Solo consulta · Ana Titular")
        self.assertContains(team, 'name="alcance" value="equipo"')

        search = self.client.get(reverse("case_list"), {"alcance": "equipo", "q": "Titular"})
        self.assertEqual([case.reference for case in search.context["cases"]], ["IA-EQ-001"])

    def test_scope_parameter_does_not_change_other_roles(self):
        self.client.force_login(self.institution)
        page = self.client.get(reverse("case_list"), {"alcance": "equipo"})
        self.assertEqual(list(page.context["cases"]), [])

    # ---------- Reserva ----------

    def test_direction_reserves_and_releases_a_case_with_justification(self):
        url = reverse("director_case_reservation", args=[self.case.pk])
        self.client.force_login(self.director)
        page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertContains(page, "Reservar expediente")
        self.assertEqual(self.client.get(url).status_code, 405)

        short = self.client.post(url, {"justification": "corto"})
        self.assertRedirects(short, reverse("case_detail", args=[self.case.pk]))
        self.case.refresh_from_db()
        self.assertFalse(self.case.is_reserved)

        self.client.post(url, {"justification": "Investigación especial por denuncia."})
        self.case.refresh_from_db()
        self.assertTrue(self.case.is_reserved)
        self.assertEqual(self.case.reservation_reason, "Investigación especial por denuncia.")
        log = ActivityLog.objects.get(action="case_reserved")
        self.assertEqual(log.details["justification"], "Investigación especial por denuncia.")

        self.client.force_login(self.teammate)
        self.assertEqual(self.client.get(reverse("case_detail", args=[self.case.pk])).status_code, 404)
        self.client.force_login(self.owner)
        owner_page = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertContains(owner_page, "Reservado")

        self.client.force_login(self.director)
        self.client.post(url, {"justification": "La investigación concluyó."})
        self.case.refresh_from_db()
        self.assertFalse(self.case.is_reserved)
        self.assertTrue(ActivityLog.objects.filter(action="case_unreserved").exists())

    def test_auditors_cannot_change_the_reservation(self):
        self.client.force_login(self.owner)
        result = self.client.post(
            reverse("director_case_reservation", args=[self.case.pk]),
            {"justification": "Quiero ocultarlo del equipo."},
        )
        self.assertEqual(result.status_code, 403)
        self.case.refresh_from_db()
        self.assertFalse(self.case.is_reserved)

    # ---------- CDE ----------

    def test_teammate_consults_cde_of_every_center(self):
        self.client.force_login(self.teammate)
        self.assertEqual(self.client.get(reverse("cde_detail", args=[self.center.pk])).status_code, 200)
        self.make_case("IA-EQ-DOS", AuditCase.Status.DRAFT, center=self.other_center)
        self.assertEqual(self.client.get(reverse("cde_detail", args=[self.other_center.pk])).status_code, 200)
