from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import TechnicalSupportRequestForm
from apps.accounts.models import User
from apps.audits.forms import AuditCaseForm, RecommendationForm

from .models import Organization


class OrganizationSearchTests(TestCase):
    password = "UnaClaveDePrueba!2026"

    def setUp(self):
        self.url = reverse("organization_search")
        self.flores = Organization.objects.create(
            code="10234", name="Centro Escolar José Matías Delgado",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.code_match = Organization.objects.create(
            code="102", name="Instituto Nacional de Apopa",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.inactive = Organization.objects.create(
            code="20001", name="Centro Escolar Cerrado",
            kind=Organization.Kind.EDUCATIONAL_CENTER, is_active=False,
        )
        self.institution_user = User.objects.create_user(
            username="10234", password=self.password,
            role=User.Role.INSTITUTION, organization=self.flores, must_change_password=False,
        )

    def login(self, role):
        user = User.objects.create_user(username=f"user-{role}", password=self.password, role=role, must_change_password=False)
        self.client.force_login(user)
        return user

    def results(self, **params):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def test_requires_login(self):
        response = self.client.get(self.url, {"q": "centro"})
        self.assertEqual(response.status_code, 302)

    def test_institutions_cannot_search_catalog(self):
        self.client.force_login(self.institution_user)
        response = self.client.get(self.url, {"q": "centro"})
        self.assertEqual(response.status_code, 403)

    def test_internal_roles_can_search(self):
        for role in (User.Role.AUDIT_MANAGER, User.Role.AUDITOR, User.Role.TECHNICAL_ADMIN):
            with self.subTest(role=role):
                self.login(role)
                self.assertEqual([item["id"] for item in self.results(q="matias")], [self.flores.pk])

    def test_matches_without_accents_and_by_every_word(self):
        self.login(User.Role.AUDIT_MANAGER)
        self.assertEqual(
            self.results(q="JOSE delgado"),
            [{"id": self.flores.pk, "text": "10234 - Centro Escolar José Matías Delgado"}],
        )
        self.assertEqual(self.results(q="jose apopa"), [])

    def test_exact_code_comes_first(self):
        self.login(User.Role.AUDIT_MANAGER)
        self.assertEqual([item["id"] for item in self.results(q="102")], [self.code_match.pk, self.flores.pk])

    def test_short_queries_return_nothing(self):
        self.login(User.Role.AUDIT_MANAGER)
        self.assertEqual(self.results(q="c"), [])

    def test_inactive_only_when_requested(self):
        self.login(User.Role.AUDIT_MANAGER)
        self.assertEqual(self.results(q="cerrado"), [])
        self.assertEqual([item["id"] for item in self.results(q="cerrado", todas="1")], [self.inactive.pk])

    def test_results_are_limited(self):
        Organization.objects.bulk_create(
            Organization(code=f"9{index:04d}", name=f"Escuela Rural {index}", kind=Organization.Kind.EDUCATIONAL_CENTER)
            for index in range(30)
        )
        self.login(User.Role.AUDIT_MANAGER)
        response = self.client.get(self.url, {"q": "escuela rural"}).json()
        self.assertEqual(len(response["results"]), 20)
        self.assertTrue(response["more"])


class OrganizationSearchWidgetTests(TestCase):
    def setUp(self):
        self.centers = [
            Organization.objects.create(
                code=f"C{index}", name=f"Centro {index}", kind=Organization.Kind.EDUCATIONAL_CENTER,
            )
            for index in range(5)
        ]

    def test_renders_only_the_selected_option(self):
        html = str(RecommendationForm(initial={"responsible_organization": self.centers[2].pk})["responsible_organization"])
        self.assertIn(f'data-org-search="{reverse("organization_search")}"', html)
        self.assertIn(f'<option value="{self.centers[2].pk}" selected>C2 - Centro 2</option>', html)
        self.assertEqual(html.count("<option"), 2)

    def test_renders_empty_option_without_value_or_with_invalid_value(self):
        self.assertEqual(str(RecommendationForm()["responsible_organization"]).count("<option"), 1)
        form = RecommendationForm(data={"responsible_organization": "no-es-un-id"})
        self.assertEqual(str(form["responsible_organization"]).count("<option"), 1)

    def test_form_still_validates_against_its_queryset(self):
        inactive = Organization.objects.create(
            code="X1", name="Inactiva", kind=Organization.Kind.EDUCATIONAL_CENTER, is_active=False,
        )
        form = RecommendationForm(data={"responsible_organization": inactive.pk})
        form.is_valid()
        self.assertIn("responsible_organization", form.errors)

    def test_support_form_searches_inactive_organizations(self):
        html = str(TechnicalSupportRequestForm()["organization"])
        self.assertIn("?todas=1", html)

    def test_auditor_keeps_full_list_of_assigned_organizations(self):
        auditor = User.objects.create_user(username="auditor", password="x", role=User.Role.AUDITOR)
        auditor.assigned_organizations.add(self.centers[0], self.centers[1])
        html = str(AuditCaseForm(user=auditor)["audited_organization"])
        self.assertNotIn("data-org-search", html)
        self.assertEqual(html.count("<option"), 3)
