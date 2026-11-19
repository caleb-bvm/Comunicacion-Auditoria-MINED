import shutil
import tempfile
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.audits.models import ActivityLog

from .models import Organization, SchoolBoardMember, SchoolBoardPeriod


class SchoolBoardTests(TestCase):
    password = "UnaClaveDePrueba!2026"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_root = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.center = Organization.objects.create(
            code="CE-CDE-01",
            name="Centro Escolar del CDE",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.other_center = Organization.objects.create(
            code="CE-CDE-02",
            name="Otro Centro Escolar",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.audit_unit = Organization.objects.create(
            code="AUD-CDE",
            name="Dirección de Auditoría",
            kind=Organization.Kind.MINISTRY_UNIT,
        )
        self.institution = User.objects.create_user(
            username="centro.cde-01",
            password=self.password,
            role=User.Role.INSTITUTION,
            organization=self.center,
            must_change_password=False,
        )
        self.other_institution = User.objects.create_user(
            username="centro.cde-02",
            password=self.password,
            role=User.Role.INSTITUTION,
            organization=self.other_center,
            must_change_password=False,
        )
        self.director = User.objects.create_user(
            username="directora-cde",
            password=self.password,
            role=User.Role.AUDIT_MANAGER,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor-cde",
            password=self.password,
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )

    @staticmethod
    def document(name="acta-cde.pdf"):
        return SimpleUploadedFile(
            name,
            b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF",
            content_type="application/pdf",
        )

    def create_period(self, **overrides):
        data = {
            "organization": self.center,
            "start_date": date(2026, 1, 1),
            "end_date": date(2027, 12, 31),
            "school_year_start": 2026,
            "school_year_end": 2027,
            "supporting_document": self.document(),
            "supporting_document_name": "acta-cde.pdf",
            "is_current": True,
            "created_by": self.institution,
            "updated_by": self.institution,
        }
        data.update(overrides)
        return SchoolBoardPeriod.objects.create(**data)

    def test_institution_creates_period_and_previous_period_becomes_historical(self):
        previous = self.create_period(
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            school_year_start=2024,
            school_year_end=2025,
        )
        self.client.force_login(self.institution)

        response = self.client.post(
            reverse("cde_period_create", args=[self.center.pk]),
            {
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
                "school_year_start": "2026",
                "school_year_end": "2027",
                "supporting_document": self.document("acta-2026.pdf"),
                "notes": "Elegido para el nuevo período.",
            },
        )

        self.assertRedirects(response, reverse("cde_detail", args=[self.center.pk]))
        previous.refresh_from_db()
        self.assertFalse(previous.is_current)
        current = SchoolBoardPeriod.objects.get(organization=self.center, is_current=True)
        self.assertEqual(current.school_year_start, 2026)
        self.assertEqual(current.supporting_document_name, "acta-2026.pdf")
        log = ActivityLog.objects.get(action="cde_period_created")
        self.assertEqual(log.actor, self.institution)
        self.assertEqual(log.details["organization_id"], self.center.pk)
        self.assertIn(previous.pk, log.details["previous_period_ids"])

    def test_institution_adds_member_and_records_departure_without_deleting_it(self):
        period = self.create_period()
        self.client.force_login(self.institution)

        added = self.client.post(
            reverse("cde_member_create", args=[period.pk]),
            {
                "full_name": "María López",
                "identity_document": "00000000-0",
                "position": "Presidenta",
                "sector": SchoolBoardMember.Sector.PARENTS,
                "is_legal_representative": "on",
                "joined_on": "2026-01-01",
            },
        )
        member = SchoolBoardMember.objects.get(period=period)
        departed = self.client.post(
            reverse("cde_member_departure", args=[member.pk]),
            {
                "left_on": "2026-08-15",
                "exit_reason": "Sustitución acordada por el CDE.",
                "change_document": self.document("sustitucion.pdf"),
            },
        )

        self.assertRedirects(added, reverse("cde_detail", args=[self.center.pk]))
        self.assertRedirects(departed, reverse("cde_detail", args=[self.center.pk]))
        member.refresh_from_db()
        self.assertEqual(member.left_on, date(2026, 8, 15))
        self.assertEqual(member.change_document_name, "sustitucion.pdf")
        self.assertTrue(SchoolBoardMember.objects.filter(pk=member.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action="cde_member_added").exists())
        self.assertTrue(ActivityLog.objects.filter(action="cde_member_departed").exists())

    def test_dui_must_use_the_salvadoran_format(self):
        period = self.create_period()
        self.client.force_login(self.institution)

        invalid = self.client.post(
            reverse("cde_member_create", args=[period.pk]),
            {
                "full_name": "Persona con DUI inválido",
                "identity_document": "000000000",
                "position": "Vocal",
                "sector": SchoolBoardMember.Sector.PARENTS,
                "joined_on": "2026-01-01",
            },
        )

        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "Ingrese el DUI con el formato 00000000-0")
        self.assertFalse(SchoolBoardMember.objects.filter(period=period).exists())

        valid = self.client.post(
            reverse("cde_member_create", args=[period.pk]),
            {
                "full_name": "Persona con DUI válido",
                "identity_document": "00000000-0",
                "position": "Vocal",
                "sector": SchoolBoardMember.Sector.PARENTS,
                "joined_on": "2026-01-01",
            },
        )

        self.assertRedirects(valid, reverse("cde_detail", args=[self.center.pk]))
        self.assertEqual(
            SchoolBoardMember.objects.get(period=period).identity_document,
            "00000000-0",
        )

    def test_correction_keeps_previous_and_new_values_in_activity_log(self):
        period = self.create_period(notes="Texto anterior")
        self.client.force_login(self.institution)

        response = self.client.post(
            reverse("cde_period_edit", args=[period.pk]),
            {
                "start_date": "2026-01-01",
                "end_date": "2027-12-31",
                "school_year_start": "2026",
                "school_year_end": "2027",
                "notes": "Texto corregido",
            },
        )

        self.assertRedirects(response, reverse("cde_detail", args=[self.center.pk]))
        log = ActivityLog.objects.get(action="cde_period_corrected")
        self.assertEqual(log.details["before"]["notes"], "Texto anterior")
        self.assertEqual(log.details["after"]["notes"], "Texto corregido")

    def test_institution_cannot_view_or_change_another_centers_cde(self):
        other_period = self.create_period(
            organization=self.other_center,
            created_by=self.other_institution,
            updated_by=self.other_institution,
        )
        self.client.force_login(self.institution)

        view_response = self.client.get(reverse("cde_detail", args=[self.other_center.pk]))
        change_response = self.client.post(
            reverse("cde_member_create", args=[other_period.pk]),
            {
                "full_name": "Persona no autorizada",
                "position": "Vocal",
                "sector": SchoolBoardMember.Sector.PARENTS,
                "joined_on": "2026-01-01",
            },
        )

        self.assertEqual(view_response.status_code, 403)
        self.assertEqual(change_response.status_code, 403)
        self.assertFalse(SchoolBoardMember.objects.filter(period=other_period).exists())

    def test_director_has_read_only_access(self):
        period = self.create_period()
        self.client.force_login(self.director)

        detail = self.client.get(reverse("cde_detail", args=[self.center.pk]))
        create = self.client.post(
            reverse("cde_member_create", args=[period.pk]),
            {
                "full_name": "Intento de Dirección",
                "position": "Vocal",
                "sector": SchoolBoardMember.Sector.PARENTS,
                "joined_on": "2026-01-01",
            },
        )

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "CDE 2026–2027")
        self.assertNotContains(detail, "Agregar integrante")
        self.assertEqual(create.status_code, 403)

    def test_every_auditor_can_consult_center_cde_without_managing_it(self):
        self.create_period()
        unassigned = User.objects.create_user(
            username="auditor-no-asignado",
            password=self.password,
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )

        self.client.force_login(unassigned)
        allowed = self.client.get(reverse("cde_detail", args=[self.center.pk]))
        create = self.client.get(reverse("cde_period_create", args=[self.center.pk]))

        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "CDE 2026–2027")
        self.assertFalse(allowed.context["can_manage"])
        self.assertEqual(create.status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("cde_detail", args=[self.center.pk]))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('cde_detail', args=[self.center.pk])}",
        )
