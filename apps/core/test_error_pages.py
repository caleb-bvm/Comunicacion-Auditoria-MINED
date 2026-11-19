import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.audits.forms import (
    AuditInquiryCreateForm,
    AuditInquiryReplyForm,
    HistoricalAttachmentForm,
    ResponseForm,
)
from apps.institutions.forms import SchoolBoardMemberDepartureForm, SchoolBoardPeriodForm
from apps.institutions.models import Organization

from .errors import bad_request, server_error
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
        self.assertContains(response, "Datos para soporte técnico", status_code=404)
        self.assertContains(response, "404 Not Found", status_code=404)
        self.assertContains(response, "GET /direccion-inexistente/", status_code=404)

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
        self.assertContains(response, "403 Forbidden (CSRF)", status_code=403)
        self.assertContains(response, "cookie de seguridad", status_code=403)
        self.assertRegex(response.content.decode(), r"<dt>Referencia</dt><dd>[0-9A-F]{8}</dd>")

    def test_server_error_page_renders_without_context(self):
        with self.assertLogs("apps.core.errors", level="ERROR") as logs:
            response = server_error(RequestFactory().get("/expedientes/5/"))

        self.assertEqual(response.status_code, 500)
        content = response.content.decode()
        self.assertIn(VIEWPORT, content)
        self.assertIn("Error del sistema", content)
        reference = re.search(r"<dt>Referencia</dt><dd>([0-9A-F]{8})</dd>", content).group(1)
        # La referencia que ve la persona es la misma que queda en el registro del servidor.
        self.assertIn(f"Referencia {reference}: error 500 en GET /expedientes/5/", logs.output[0])
        self.assertIn(f'grep -A 40 "Referencia {reference}"', content)

    def test_error_pages_hide_secret_links_and_query_strings(self):
        self.client.force_login(self.institution_user)
        response = self.client.get("/activar-cuenta/MQ/abc-secret-token/extra/?token=otro")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "GET /activar-cuenta/[oculto]/", status_code=404)
        self.assertNotContains(response, "abc-secret-token", status_code=404)
        self.assertNotContains(response, "otro", status_code=404)

    def test_method_not_allowed_page_explains_the_action(self):
        self.client.force_login(self.institution_user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertTemplateUsed(response, "405.html")
        self.assertEqual(response["Allow"], "POST, OPTIONS")
        self.assertContains(response, "Esta acción no se puede abrir así", status_code=405)
        self.assertContains(response, "Métodos permitidos: POST, OPTIONS.", status_code=405)
        self.assertContains(response, 'class="mobile-navigation"', status_code=405)

    def test_method_not_allowed_keeps_head_responses_empty(self):
        response = self.client.head(reverse("logout"))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.content, b"")

    def test_bad_request_page_renders_without_context(self):
        response = bad_request(RequestFactory().get("/"), SuspiciousOperation())

        self.assertEqual(response.status_code, 400)
        content = response.content.decode()
        self.assertIn(VIEWPORT, content)
        self.assertIn("Solicitud no válida", content)


class OfflineSupportTests(TestCase):
    def test_offline_page_has_no_session_data(self):
        user = User.objects.create_user(username="auditor", role=User.Role.AUDITOR, must_change_password=False)
        self.client.force_login(user)

        response = self.client.get(reverse("offline"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo conectar con el sistema")
        self.assertContains(response, "Datos para soporte técnico")
        self.assertNotContains(response, "mobile-navigation")
        self.assertNotContains(response, "csrfmiddlewaretoken")

    def test_service_worker_caches_only_the_offline_page_and_its_assets(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript; charset=utf-8")
        script = response.content.decode()
        self.assertIn('const OFFLINE_URL = "/sin-conexion/";', script)
        self.assertRegex(script, r'const CACHE_NAME = "siga-sin-conexion-[0-9a-f]{12}";')
        offline_page = self.client.get(reverse("offline")).content.decode()
        for asset in re.findall(r'(?:href|src)="(/static/[^"]+)"', offline_page):
            with self.subTest(asset=asset):
                self.assertIn(f'"{asset}"', script)

    def test_service_worker_and_offline_page_skip_the_password_change_redirect(self):
        user = User.objects.create_user(username="nuevo", role=User.Role.AUDITOR, must_change_password=True)
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("service_worker")).status_code, 200)
        self.assertEqual(self.client.get(reverse("offline")).status_code, 200)


class NginxErrorPageTests(TestCase):
    DEPLOY = Path(settings.BASE_DIR) / "deploy"

    def test_every_nginx_error_page_exists_and_explains_the_failure(self):
        config = (self.DEPLOY / "nginx.conf").read_text(encoding="utf-8")
        pages = set(re.findall(r"error_page [0-9 ]+ /_errores/([0-9]+\.html);", config))

        self.assertEqual(pages, {"413.html", "429.html", "502.html", "504.html"})
        for page in pages:
            with self.subTest(page=page):
                html = (self.DEPLOY / "errors" / page).read_text(encoding="utf-8")
                self.assertIn('<meta name="viewport"', html)
                self.assertIn("Datos para soporte técnico", html)
                self.assertIn('<!--# echo var="siga_error_path"', html)
                self.assertIn('<!--# echo var="time_local"', html)


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
