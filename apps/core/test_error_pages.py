from django.core.exceptions import SuspiciousOperation
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.views.defaults import bad_request, server_error

from apps.accounts.models import User
from apps.audits.forms import (
    AuditInquiryCreateForm,
    AuditInquiryReplyForm,
    HistoricalAttachmentForm,
    ResponseForm,
)
from apps.institutions.forms import SchoolBoardMemberDepartureForm, SchoolBoardPeriodForm
from apps.institutions.models import Organization

from .validators import ALLOWED_EXTENSIONS, EVIDENCE_ACCEPT

VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'


class ErrorPageTests(TestCase):
    def setUp(self):
        self.center = Organization.objects.create(
            code="CE-1",
            name="Centro Escolar Uno",
            kind=Organization.Kind.EDUCATIONAL_CENTER,
        )
        self.institution_user = User.objects.create_user(
            username="CE-1",
            role=User.Role.INSTITUTION,
            organization=self.center,
            must_change_password=False,
        )

    def test_not_found_page_is_mobile_ready(self):
        response = self.client.get("/direccion-inexistente/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, VIEWPORT, status_code=404, html=False)
        self.assertContains(response, "Página no encontrada", status_code=404)

    def test_permission_denied_keeps_navigation_and_explains_reason(self):
        self.client.force_login(self.institution_user)

        response = self.client.get(reverse("case_create"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, VIEWPORT, status_code=403, html=False)
        self.assertContains(response, "Esta acción corresponde al personal auditor autorizado.", status_code=403)
        self.assertContains(response, 'class="mobile-navigation"', status_code=403)

    def test_csrf_failure_page_explains_expired_form(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(reverse("login"), {"username": "CE-1", "password": "x"})

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403_csrf.html")
        self.assertContains(response, VIEWPORT, status_code=403, html=False)
        self.assertContains(response, "El formulario ya no es válido", status_code=403)

    def test_server_error_page_renders_without_context(self):
        response = server_error(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn(VIEWPORT, content)
        self.assertIn("Error del sistema", content)

    def test_bad_request_page_renders_without_context(self):
        response = bad_request(RequestFactory().get("/"), SuspiciousOperation())

        self.assertEqual(response.status_code, 400)
        content = response.content.decode()
        self.assertIn(VIEWPORT, content)
        self.assertIn("Solicitud no válida", content)


class EvidenceFileAcceptTests(TestCase):
    def test_accept_lists_every_allowed_extension(self):
        self.assertEqual(set(EVIDENCE_ACCEPT.split(",")), ALLOWED_EXTENSIONS)

    def test_evidence_file_inputs_filter_the_device_picker(self):
        fields = [
            (AuditInquiryCreateForm, "attachment"),
            (AuditInquiryReplyForm, "attachment"),
            (HistoricalAttachmentForm, "file"),
            (ResponseForm, "files"),
            (SchoolBoardPeriodForm, "supporting_document"),
            (SchoolBoardMemberDepartureForm, "change_document"),
        ]
        for form_class, field_name in fields:
            with self.subTest(form=form_class.__name__, field=field_name):
                widget = form_class.base_fields[field_name].widget
                self.assertEqual(widget.attrs.get("accept"), EVIDENCE_ACCEPT)

    def test_response_files_input_still_allows_multiple_files(self):
        rendered = ResponseForm.base_fields["files"].widget.render("files", None)

        self.assertIn("multiple", rendered)
        self.assertIn(f'accept="{EVIDENCE_ACCEPT}"', rendered)
