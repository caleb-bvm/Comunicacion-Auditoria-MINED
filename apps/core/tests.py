from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.audits.models import AuditCase, CaseDecision
from apps.institutions.models import Organization

from .context_processors import sidebar_context


class SidebarContextTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.audit_unit = Organization.objects.create(
            code="DAI",
            name="Dirección de Auditoría Interna",
            kind=Organization.Kind.MINISTRY_UNIT,
        )
        self.center = Organization.objects.create(
            code="CE-1",
            name="Centro Escolar Uno",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.other_center = Organization.objects.create(
            code="CE-2",
            name="Centro Escolar Dos",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.auditor = User.objects.create_user(
            username="auditor",
            role=User.Role.AUDITOR,
            organization=self.audit_unit,
        )

    def get_sidebar_context(self, user):
        request = self.factory.get("/")
        request.user = user
        return sidebar_context(request).get("sidebar_context")

    def create_case(self, reference, organization):
        return AuditCase.objects.create(
            reference=reference,
            title="Auditoría de prueba",
            audited_organization=organization,
            assigned_auditor=self.auditor,
            created_by=self.auditor,
        )

    def test_auditor_context_counts_distinct_assigned_organizations(self):
        self.create_case("IA-001", self.center)
        self.create_case("IA-002", self.center)
        self.create_case("IA-003", self.other_center)

        context = self.get_sidebar_context(self.auditor)

        self.assertEqual(context["label"], "Instituciones asignadas")
        self.assertEqual(context["value"], "2 instituciones")

    def test_request_without_user_returns_empty_context(self):
        self.assertEqual(sidebar_context(self.factory.get("/")), {})

    def test_institution_context_is_omitted_as_redundant(self):
        institution_user = User.objects.create_user(
            username="centro",
            role=User.Role.INSTITUTION,
            organization=self.center,
        )

        context = self.get_sidebar_context(institution_user)

        self.assertIsNone(context)

    def test_audit_manager_context_shows_pending_decisions(self):
        manager = User.objects.create_user(
            username="directora",
            role=User.Role.AUDIT_MANAGER,
            organization=self.audit_unit,
        )
        case = self.create_case("IA-004", self.center)
        CaseDecision.objects.create(
            case=case,
            kind=CaseDecision.Kind.PUBLICATION,
            requested_by=self.auditor,
        )

        context = self.get_sidebar_context(manager)

        self.assertEqual(context["label"], "Decisiones pendientes")
        self.assertEqual(context["value"], "1 decisión pendiente")

    def test_technical_admin_context_shows_active_users(self):
        technical_admin = User.objects.create_user(
            username="tecnico",
            role=User.Role.TECHNICAL_ADMIN,
            organization=self.audit_unit,
        )

        context = self.get_sidebar_context(technical_admin)

        self.assertEqual(context["label"], "Administración del sistema")
        self.assertEqual(context["value"], "2 usuarios activos")

    def test_anonymous_user_has_no_sidebar_context(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        self.assertEqual(sidebar_context(request), {})
