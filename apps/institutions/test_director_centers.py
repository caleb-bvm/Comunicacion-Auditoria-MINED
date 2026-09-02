from datetime import date, timedelta

from django.contrib.auth.hashers import check_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audits.models import (
    ActivityLog,
    AuditCase,
    DeadlineExtension,
    Finding,
    Recommendation,
)

from .models import Organization, SchoolBoardPeriod


class DirectorEducationalCenterTests(TestCase):
    common_password = "UnaClaveDePrueba!2026"

    def setUp(self):
        self.audit_unit = Organization.objects.create(
            code="DAI",
            name="Dirección de Auditoría Interna",
            kind=Organization.Kind.MINISTRY_UNIT,
        )
        self.center = Organization.objects.create(
            code="CE-104",
            name="Instituto Nacional Central",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            department="San Salvador",
            municipality="San Salvador",
            is_active=False,
        )
        self.other_center = Organization.objects.create(
            code="CE-205",
            name="Centro Escolar Las Flores",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
            department="La Libertad",
            municipality="Santa Tecla",
        )
        self.director = User.objects.create_user(
            username="directora",
            password=self.common_password,
            role=User.Role.AUDIT_MANAGER,
            organization=self.audit_unit,
            must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            password=self.common_password,
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
            must_change_password=False,
        )

    def test_director_can_search_centers_by_name_or_code(self):
        self.client.force_login(self.director)

        by_code = self.client.get(
            reverse("director_educational_centers"), {"q": "CE-104"}
        )
        by_name = self.client.get(
            reverse("director_educational_centers"), {"q": "Nacional Central"}
        )

        for response in (by_code, by_name):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Instituto Nacional Central")
            self.assertNotContains(response, "Centro Escolar Las Flores")
            self.assertContains(response, "Activar")

    def test_center_search_does_not_duplicate_geographic_filters(self):
        self.client.force_login(self.director)
        url = reverse("director_educational_centers")

        text_search = self.client.get(url, {"q": "San Salvador"})
        geographic_search = self.client.get(
            url, {"department": "San Salvador", "municipality": "San Salvador"}
        )

        self.assertNotContains(text_search, self.center.name)
        self.assertContains(geographic_search, self.center.name)
        self.assertNotContains(geographic_search, self.other_center.name)

    def test_center_directory_exposes_three_search_controls_and_priority_shortcuts(self):
        self.client.force_login(self.director)

        response = self.client.get(reverse("director_educational_centers"))

        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'name="department"')
        self.assertContains(response, 'name="municipality"')
        for removed_filter in ("district", "attention", "risk", "audits", "cde", "access"):
            self.assertNotContains(response, f'name="{removed_filter}"')
        self.assertContains(response, "Atención inmediata")
        self.assertContains(response, "Próximos a vencer")
        self.assertContains(response, "Sin acceso")
        self.assertContains(response, "Sin CDE vigente")
        self.assertContains(response, "attention=immediate")
        self.assertContains(response, "attention=due_soon")
        self.assertContains(response, "access=pending")
        self.assertContains(response, "cde=pending")

    def test_director_can_open_cases_filtered_by_center(self):
        center_case = AuditCase.objects.create(
            reference="IA-CENTRO-104",
            title="Expediente del centro seleccionado",
            audited_organization=self.center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        other_case = AuditCase.objects.create(
            reference="IA-CENTRO-205",
            title="Expediente de otro centro",
            audited_organization=self.other_center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.director)

        directory = self.client.get(reverse("director_educational_centers"))
        cases = self.client.get(reverse("case_list"), {"organization": self.center.pk})

        self.assertContains(
            directory,
            f'{reverse("case_list")}?organization={self.center.pk}',
        )
        listed_center = next(
            center for center in directory.context["centers"] if center.pk == self.center.pk
        )
        self.assertEqual(listed_center.case_count, 1)
        self.assertContains(cases, self.center.name)
        self.assertContains(cases, center_case.reference)
        self.assertNotContains(cases, other_case.reference)
        self.assertContains(cases, "Volver a centros")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("director_educational_centers"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('director_educational_centers')}",
        )

    def test_invalid_center_filter_does_not_crash_or_show_unfiltered_cases(self):
        AuditCase.objects.create(
            reference="IA-NO-DEBE-MOSTRARSE",
            title="Expediente fuera del filtro inválido",
            audited_organization=self.center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        self.client.force_login(self.director)

        malformed = self.client.get(reverse("case_list"), {"organization": "centro-invalido"})
        missing = self.client.get(reverse("case_list"), {"organization": "999999"})

        for response in (malformed, missing):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Centro educativo no encontrado")
            self.assertNotContains(response, "IA-NO-DEBE-MOSTRARSE")

    def test_center_list_and_activation_are_restricted_to_director(self):
        self.client.force_login(self.auditor)

        list_response = self.client.get(reverse("director_educational_centers"))
        activation_response = self.client.post(
            reverse("director_activate_educational_center", args=[self.center.pk])
        )

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(activation_response.status_code, 403)
        self.assertFalse(
            User.objects.filter(
                organization=self.center,
                role=User.Role.INSTITUTION,
            ).exists()
        )

    def test_director_activates_center_with_common_credential_and_audit_log(self):
        self.client.force_login(self.director)

        response = self.client.post(
            reverse("director_activate_educational_center", args=[self.center.pk])
        )

        self.assertRedirects(response, reverse("director_educational_centers"))
        account = User.objects.get(
            organization=self.center,
            role=User.Role.INSTITUTION,
        )
        self.assertEqual(account.username, "centro.ce-104")
        self.assertTrue(account.is_active)
        self.assertFalse(account.must_change_password)
        self.assertTrue(check_password(self.common_password, account.password))
        self.assertEqual(account.password, self.director.password)
        self.client.logout()
        self.assertTrue(
            self.client.login(username=account.username, password=self.common_password)
        )
        self.center.refresh_from_db()
        self.assertTrue(self.center.is_active)
        log = ActivityLog.objects.get(action="educational_center_activated")
        self.assertEqual(log.actor, self.director)
        self.assertEqual(log.target_id, str(self.center.pk))
        self.assertEqual(log.details["username"], "centro.ce-104")
        self.assertTrue(log.details["account_created"])

    def test_activation_reuses_suspended_account_without_creating_a_duplicate(self):
        account = User.objects.create_user(
            username="centro.existente",
            password="ClaveAnterior!2026",
            role=User.Role.INSTITUTION,
            organization=self.other_center,
            is_active=False,
            must_change_password=True,
        )
        self.client.force_login(self.director)

        self.client.post(
            reverse("director_activate_educational_center", args=[self.other_center.pk])
        )

        account.refresh_from_db()
        self.assertTrue(account.is_active)
        self.assertFalse(account.must_change_password)
        self.assertEqual(account.password, self.director.password)
        self.assertEqual(
            User.objects.filter(
                organization=self.other_center,
                role=User.Role.INSTITUTION,
            ).count(),
            1,
        )

    def _listed_center(self, response, center):
        return next(item for item in response.context["centers"] if item.pk == center.pk)

    def _published_recommendation(
        self,
        *,
        audited_center,
        responsible_center,
        reference,
        risk=Finding.RiskLevel.MEDIUM,
        status=Recommendation.Status.PENDING,
        deadline=None,
    ):
        case = AuditCase.objects.create(
            reference=reference,
            title=f"Auditoría {reference}",
            audited_organization=audited_center,
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        finding = Finding.objects.create(
            case=case,
            number=1,
            title="Hallazgo institucional de prueba",
            risk_level=risk,
        )
        recommendation = Recommendation.objects.create(
            finding=finding,
            number=1,
            text="Atender la condición identificada por Auditoría.",
            responsible_organization=responsible_center,
            status=status,
            deadline=deadline,
        )
        return case, finding, recommendation

    def test_directory_includes_centers_without_audits_and_marks_compliance_as_not_available(self):
        self.client.force_login(self.director)

        response = self.client.get(reverse("director_educational_centers"), {"audits": "no"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.center.name)
        self.assertContains(response, self.other_center.name)
        listed = self._listed_center(response, self.center)
        self.assertEqual(listed.case_count, 0)
        self.assertIsNone(listed.compliance_rate)
        self.assertContains(response, "N/D")

    def test_risk_is_attributed_to_audited_center_and_overdue_to_responsible_center(self):
        self._published_recommendation(
            audited_center=self.center,
            responsible_center=self.other_center,
            reference="IA-ATRIBUCION-001",
            risk=Finding.RiskLevel.CRITICAL,
            deadline=date.today() - timedelta(days=2),
        )
        self.client.force_login(self.director)

        response = self.client.get(reverse("director_educational_centers"))
        audited = self._listed_center(response, self.center)
        responsible = self._listed_center(response, self.other_center)

        self.assertEqual(audited.critical_active_count, 1)
        self.assertEqual(audited.obligation_count, 0)
        self.assertEqual(audited.overdue_count, 0)
        self.assertEqual(responsible.critical_active_count, 0)
        self.assertEqual(responsible.obligation_count, 1)
        self.assertEqual(responsible.overdue_count, 1)

    def test_drafts_do_not_affect_consolidated_center_indicators(self):
        draft = AuditCase.objects.create(
            reference="IA-BORRADOR-CENTRO",
            title="Expediente aún no publicado",
            audited_organization=self.center,
            status=AuditCase.Status.DRAFT,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )
        finding = Finding.objects.create(
            case=draft,
            number=1,
            title="Riesgo crítico provisional",
            risk_level=Finding.RiskLevel.CRITICAL,
        )
        Recommendation.objects.create(
            finding=finding,
            number=1,
            text="Recomendación provisional.",
            responsible_organization=self.center,
            deadline=date.today() - timedelta(days=20),
        )
        self.client.force_login(self.director)

        response = self.client.get(reverse("director_educational_centers"))
        listed = self._listed_center(response, self.center)

        self.assertEqual(listed.case_count, 0)
        self.assertEqual(listed.provisional_case_count, 1)
        self.assertEqual(listed.critical_active_count, 0)
        self.assertEqual(listed.overdue_count, 0)
        self.assertEqual(listed.obligation_count, 0)

    def test_center_alerts_use_latest_deadline_extension(self):
        _, _, recommendation = self._published_recommendation(
            audited_center=self.center,
            responsible_center=self.center,
            reference="IA-PRORROGA-CENTRO",
            deadline=date.today() - timedelta(days=2),
        )
        DeadlineExtension.objects.create(
            recommendation=recommendation,
            previous_deadline=recommendation.deadline,
            business_days=5,
            new_deadline=date.today() + timedelta(days=5),
            reason="Prórroga vigente para completar las evidencias.",
            granted_by=self.auditor,
        )
        self.client.force_login(self.director)

        response = self.client.get(reverse("director_educational_centers"))
        due_soon = self.client.get(
            reverse("director_educational_centers"), {"attention": "due_soon"}
        )
        listed = self._listed_center(response, self.center)

        self.assertEqual(listed.overdue_count, 0)
        self.assertEqual(listed.due_soon_count, 1)
        self.assertContains(due_soon, self.center.name)
        self.assertNotContains(due_soon, self.other_center.name)

    def test_cde_must_be_marked_current_and_inside_its_date_range(self):
        SchoolBoardPeriod.objects.create(
            organization=self.center,
            start_date=date.today() - timedelta(days=400),
            end_date=date.today() - timedelta(days=30),
            school_year_start=date.today().year - 1,
            school_year_end=date.today().year,
            supporting_document=SimpleUploadedFile("cde.pdf", b"documento"),
            supporting_document_name="cde.pdf",
            is_current=True,
            created_by=self.director,
            updated_by=self.director,
        )
        self.client.force_login(self.director)

        directory = self.client.get(reverse("director_educational_centers"))
        detail = self.client.get(
            reverse("director_educational_center_detail", args=[self.center.pk])
        )
        listed = self._listed_center(directory, self.center)

        self.assertFalse(listed.has_current_cde)
        self.assertEqual(listed.cde_state, "expired")
        self.assertIsNone(detail.context["current_cde"])
        self.assertContains(detail, "CDE vencido")

    def test_center_detail_exposes_both_analytic_roles_and_is_director_only(self):
        self._published_recommendation(
            audited_center=self.center,
            responsible_center=self.other_center,
            reference="IA-FICHA-001",
            risk=Finding.RiskLevel.HIGH,
            deadline=date.today() - timedelta(days=1),
        )
        url = reverse("director_educational_center_detail", args=[self.other_center.pk])
        self.client.force_login(self.director)

        allowed = self.client.get(url)

        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Situación auditada")
        self.assertContains(allowed, "Obligaciones y cumplimiento")
        self.assertContains(allowed, "IA-FICHA-001")
        self.assertEqual(len(allowed.context["obligations"]), 1)

        self.client.force_login(self.auditor)
        forbidden = self.client.get(url)
        self.assertEqual(forbidden.status_code, 403)

        self.client.logout()
        anonymous = self.client.get(url)
        self.assertRedirects(anonymous, f"{reverse('login')}?next={url}")
