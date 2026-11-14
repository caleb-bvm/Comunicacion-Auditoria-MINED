import gzip
import io

from django.http import FileResponse, HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase

from apps.core.middleware import PageCompressionMiddleware


class PageCompressionMiddlewareTests(SimpleTestCase):
    def process(self, response, accept="gzip, deflate"):
        request = RequestFactory().get("/", HTTP_ACCEPT_ENCODING=accept)
        return PageCompressionMiddleware(lambda _request: response)(request)

    def test_compresses_html_pages(self):
        body = "<option>Centro escolar</option>" * 500
        response = self.process(HttpResponse(body))
        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertEqual(gzip.decompress(response.content).decode(), body)
        self.assertIn("Accept-Encoding", response["Vary"])

    def test_compresses_json(self):
        response = self.process(JsonResponse({"items": ["x" * 50] * 50}))
        self.assertEqual(response["Content-Encoding"], "gzip")

    def test_leaves_binary_exports_and_files_untouched(self):
        pdf = HttpResponse(b"%PDF-1.7" + b"0" * 5000, content_type="application/pdf")
        self.assertFalse(self.process(pdf).has_header("Content-Encoding"))
        streamed = FileResponse(io.BytesIO(b"x" * 5000), content_type="text/html")
        self.assertFalse(self.process(streamed).has_header("Content-Encoding"))

    def test_respects_clients_without_gzip(self):
        response = self.process(HttpResponse("<p>x</p>" * 500), accept="identity")
        self.assertFalse(response.has_header("Content-Encoding"))
