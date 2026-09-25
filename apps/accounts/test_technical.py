import re

from django.core import mail
from django.core.cache import cache
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.audits.models import ActivityLog, AuditCase
from apps.institutions.models import Organization

from .models import TechnicalSupportRequest, User


class TechnicalAdministrationTests(TestCase):
    def setUp(self):
        self.unit = Organization.objects.create(
            code="TECH", name="Unidad técnica", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.center = Organization.objects.create(
            code="CE-TECH", name="Centro protegido", kind=Organization.Kind.EDUCATIONAL_CENTER
        )
        self.admin = User.objects.create_user(
            username="tecnico", password="ClaveTecnica!2026", role=User.Role.TECHNICAL_ADMIN,
            organization=self.unit, must_change_password=False,
        )
        self.auditor = User.objects.create_user(
            username="auditor.tech", password="ClaveAuditor!2026", role=User.Role.AUDITOR,
            organization=self.unit, must_change_password=False,
        )
        self.case = AuditCase.objects.create(
            reference="IA-TECH-001", title="Expediente protegido",
            audited_organization=self.center, assigned_auditor=self.auditor,
            created_by=self.auditor,
        )

    def test_dashboard_redirects_to_technical_console(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("technical_dashboard"))
        response = self.client.get(reverse("technical_dashboard"))
        self.assertContains(response, "Administración técnica")

    def test_non_technical_user_cannot_open_console(self):
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(reverse("technical_dashboard")).status_code, 403)

    def test_technical_admin_cannot_open_audit_case(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("case_detail", args=[self.case.pk])).status_code, 404)

    def test_suspend_requires_reason_and_is_logged(self):
        self.client.force_login(self.admin)
        url = reverse("technical_user_action", args=[self.auditor.pk, "suspend"])
        self.client.post(url, {"reason": "corto"})
        self.auditor.refresh_from_db()
        self.assertTrue(self.auditor.is_active)

        response = self.client.post(url, {"reason": "Incidente de acceso confirmado"})
        self.assertRedirects(response, reverse("technical_user_detail", args=[self.auditor.pk]))
        self.auditor.refresh_from_db()
        self.assertFalse(self.auditor.is_active)
        event = ActivityLog.objects.get(action="technical_user_suspend")
        self.assertEqual(event.details["reason"], "Incidente de acceso confirmado")

    def test_admin_cannot_suspend_itself(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("technical_user_action", args=[self.admin.pk, "suspend"]),
            {"reason": "Intento de autosuspensión técnica"},
        )
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_BASE_URL="https://auditoria.example",
)
class PublicPasswordSupportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.unit = Organization.objects.create(
            code="SUPPORT", name="Unidad de soporte", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.user = User.objects.create_user(
            username="persona.support", email="registrado@example.test",
            password="ClaveAnterior!2026", role=User.Role.AUDITOR,
            organization=self.unit, must_change_password=False,
        )
        self.admin = User.objects.create_user(
            username="admin.support", password="ClaveTecnica!2026",
            role=User.Role.TECHNICAL_ADMIN, organization=self.unit,
            must_change_password=False,
        )

    def test_login_exposes_support_entrypoint(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("password_reset_request"))
        self.assertNotContains(response, reverse("password_support_request"))

    def test_password_reset_page_routes_other_problems_to_support(self):
        response = self.client.get(reverse("password_reset_request"))
        self.assertContains(response, reverse("password_support_request"))
        self.assertContains(response, "¿Tiene otro problema de acceso?")

    def test_password_reset_is_automatic_and_does_not_create_support_request(self):
        response = self.client.post(reverse("password_reset_request"), {
            "identifier": self.user.username,
        })
        self.assertEqual(response.status_code, 202)
        self.assertNotContains(response, self.user.username, status_code=202)
        self.assertFalse(TechnicalSupportRequest.objects.exists())
        self.assertEqual(mail.outbox[0].to, ["registrado@example.test"])
        self.assertIn("https://auditoria.example/restablecer/", mail.outbox[0].body)
        self.assertTrue(ActivityLog.objects.filter(action="password_reset_email_sent").exists())

    def test_unknown_account_gets_same_neutral_response_without_email(self):
        response = self.client.post(reverse("password_reset_request"), {"identifier": "no-existe"})
        self.assertEqual(response.status_code, 202)
        self.assertContains(response, "Si existe una cuenta activa", status_code=202)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(TechnicalSupportRequest.objects.exists())

    def test_password_change_closes_existing_sessions_and_is_single_use(self):
        active_session = Client()
        self.assertTrue(active_session.login(username=self.user.username, password="ClaveAnterior!2026"))
        session_key = active_session.session.session_key
        self.client.post(reverse("password_reset_request"), {"identifier": self.user.email})
        path = re.search(r"https://auditoria\.example(/restablecer/\S+)", mail.outbox[0].body).group(1)
        visitor = Client()
        response = visitor.get(path)
        self.assertEqual(response.status_code, 302)
        form_path = response.url
        new_password = "NuevaClaveSegura!2026"
        self.assertRedirects(visitor.post(form_path, {
            "new_password1": new_password, "new_password2": new_password,
        }), reverse("login"))
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        self.assertTrue(visitor.login(username=self.user.username, password=new_password))
        self.assertContains(Client().get(path), "Este enlace ya no es válido")
        self.assertTrue(ActivityLog.objects.filter(action="password_reset_completed").exists())

    def test_support_form_no_longer_accepts_password_reset_category(self):
        response = self.client.post(reverse("password_support_request"), {
            "category": TechnicalSupportRequest.Category.PASSWORD_RESET,
            "full_name": "Persona Solicitante", "identifier": self.user.username,
            "contact_email": "contacto@example.test",
            "description": "No puedo acceder con mi contraseña habitual.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TechnicalSupportRequest.objects.exists())

    def test_technical_admin_can_filter_requests_by_category(self):
        TechnicalSupportRequest.objects.create(
            category=TechnicalSupportRequest.Category.TECHNICAL_ERROR,
            subject="Error de acceso", description="El sistema no permite continuar.",
            requester_identifier="cuenta.error", is_public_request=True,
        )
        TechnicalSupportRequest.objects.create(
            category=TechnicalSupportRequest.Category.PASSWORD_RESET,
            subject="Contraseña", description="La contraseña fue olvidada.",
            requested_by=self.user, is_public_request=True,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("technical_support_requests"),
            {"category": TechnicalSupportRequest.Category.TECHNICAL_ERROR},
        )
        self.assertContains(response, "Error de acceso")
        self.assertNotContains(response, "La contraseña fue olvidada")


class DirectorGovernanceTests(TestCase):
    def setUp(self):
        self.unit = Organization.objects.create(
            code="DAI-GOV", name="Dirección de Auditoría", kind=Organization.Kind.MINISTRY_UNIT
        )
        self.center = Organization.objects.create(
            code="CE-GOV", name="Centro gobernado", kind=Organization.Kind.EDUCATIONAL_CENTER,
            email="centro@example.test",
        )
        self.director = User.objects.create_user(
            username="direccion.gov", password="ClaveDireccion!2026",
            role=User.Role.AUDIT_MANAGER, organization=self.unit, must_change_password=False,
        )
        self.technical = User.objects.create_user(
            username="tecnico.gov", password="ClaveTecnica!2026",
            role=User.Role.TECHNICAL_ADMIN, organization=self.unit, must_change_password=False,
        )
        self.institution = User.objects.create_user(
            username="CE-GOV", password="ClaveCentro!2026",
            role=User.Role.INSTITUTION, organization=self.center, must_change_password=False,
        )

    def test_director_governance_pages_render(self):
        self.client.force_login(self.director)
        for name in (
            "director_access_accounts", "director_alerts", "director_activity",
            "director_technical_requests",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_director_can_suspend_institution_with_reason(self):
        self.client.force_login(self.director)
        url = reverse("director_suspend_institutional_account", args=[self.institution.pk])
        self.client.post(url, {"reason": "Solicitud formal por cambio de responsable"})
        self.institution.refresh_from_db()
        self.assertFalse(self.institution.is_active)
        self.assertTrue(ActivityLog.objects.filter(action="institutional_account_suspended").exists())

    def test_institution_sidebar_opens_scoped_technical_support(self):
        TechnicalSupportRequest.objects.create(
            category=TechnicalSupportRequest.Category.TECHNICAL_ERROR,
            subject="Solicitud ajena", description="No debe mostrarse a otra organización.",
            organization=self.unit, requested_by=self.director,
        )
        self.client.force_login(self.institution)
        response = self.client.get(reverse("institution_technical_support"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Soporte técnico")
        self.assertContains(response, reverse("institution_technical_support"))
        self.assertNotContains(response, "Solicitud ajena")

        response = self.client.post(reverse("institution_technical_support"), {
            "category": TechnicalSupportRequest.Category.TECHNICAL_ERROR,
            "subject": "Error en el perfil institucional",
            "description": "La pantalla no permite completar la operación requerida.",
        })
        self.assertRedirects(response, reverse("institution_technical_support"))
        support_request = TechnicalSupportRequest.objects.get(
            subject="Error en el perfil institucional"
        )
        self.assertEqual(support_request.requested_by, self.institution)
        self.assertEqual(support_request.organization, self.center)
        self.assertTrue(ActivityLog.objects.filter(
            action="technical_support_requested", target_id=str(support_request.pk)
        ).exists())

    def test_non_institution_cannot_open_institution_support(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(reverse("institution_technical_support")).status_code, 403)

    def test_support_request_flows_from_director_to_technical_admin(self):
        self.client.force_login(self.director)
        self.client.post(reverse("director_technical_requests"), {
            "category": TechnicalSupportRequest.Category.CLOSE_SESSIONS,
            "subject": "Cerrar sesiones del centro",
            "organization": self.center.pk,
            "description": "Se confirmó un cambio de responsable institucional.",
        })
        support_request = TechnicalSupportRequest.objects.get()
        self.assertEqual(support_request.status, TechnicalSupportRequest.Status.OPEN)

        self.client.force_login(self.technical)
        response = self.client.post(
            reverse("technical_support_request_detail", args=[support_request.pk]),
            {"status": TechnicalSupportRequest.Status.RESOLVED,
             "resolution": "Las sesiones activas fueron cerradas."},
        )
        self.assertRedirects(
            response, reverse("technical_support_request_detail", args=[support_request.pk])
        )
        support_request.refresh_from_db()
        self.assertEqual(support_request.status, TechnicalSupportRequest.Status.RESOLVED)
        self.assertEqual(support_request.handled_by, self.technical)

    def test_auditor_cannot_open_governance_pages(self):
        auditor = User.objects.create_user(
            username="auditor.gov", password="ClaveAuditor!2026",
            role=User.Role.AUDITOR, organization=self.unit, must_change_password=False,
        )
        self.client.force_login(auditor)
        self.assertEqual(self.client.get(reverse("director_access_accounts")).status_code, 403)
