import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization
from .models import ActivityLog, AuditCase, AuditDocument, DeadlineExtension, Response


class HistoricalBulkTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        self.storage = Path(storage.name)
        override = override_settings(MEDIA_ROOT=storage.name)
        override.enable()
        self.addCleanup(override.disable)
        self.center = Organization.objects.create(code="00012", name="Centro del lote", kind="educational_center", is_active=False)
        self.other = Organization.objects.create(code="00013", name="Otro", kind="educational_center")
        self.auditor = User.objects.create_user(username="auditor.bulk", role="auditor", must_change_password=False)
        self.director = User.objects.create_user(username="director.bulk", role="audit_manager", must_change_password=False)
        self.institution = User.objects.create_user(username="00012", role="institution", organization=self.center, must_change_password=False)
        self.client.force_login(self.auditor)
        self.url = reverse("historical_bulk_file", args=[self.center.pk])
        self.page = reverse("center_historical_bulk_upload", args=[self.center.pk])

    def data(self, content="original", **changes):
        return {"document_type": "historical_report", "title": "Informe original", "reference": "IA-2016",
                "document_date": "2016-05-12", "visibility": "audit_only",
                "file": SimpleUploadedFile("informe.pdf", f"%PDF-1.4\n{content}".encode()), **changes}

    def report(self, content="original", url=None):
        response = self.client.post(url or self.url, self.data(content))
        self.assertEqual(response.status_code, 200, response.content)
        return AuditDocument.objects.get(pk=response.json()["report_id"])

    def test_director_and_auditor_have_entry_search_and_upload_access(self):
        for user in (self.director, self.auditor):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                self.assertContains(self.client.get(reverse("historical_document_list")), reverse("historical_bulk_upload"))
                search = self.client.get(reverse("historical_bulk_upload"), {"q": "00012"})
                self.assertContains(search, self.page)
                self.assertContains(self.client.get(self.page), "Centro del lote")
                report = self.report(user.username)
                self.assertEqual(report.uploaded_by, user)
                self.assertContains(self.client.get(reverse("historical_document_detail", args=[report.pk])), "Carga múltiple")
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(reverse("director_educational_center_detail", args=[self.center.pk])).status_code, 403)

    def test_institution_and_anonymous_cannot_use_import_endpoints(self):
        self.client.force_login(self.institution)
        self.assertEqual(self.client.get(reverse("historical_bulk_upload")).status_code, 403)
        self.assertEqual(self.client.get(self.page).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.page).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.data()).status_code, 302)
        self.assertFalse(AuditDocument.objects.exists())

    def test_existing_and_new_reports_keep_dates_and_do_not_start_live_workflows(self):
        report = self.report()
        another = self.report("segundo")
        for index, parent in enumerate((report, another)):
            result = self.client.post(self.url, self.data(f"anexo-{index}", document_type="historical_response",
                parent_report=parent.pk, document_date="", organization=self.other.pk))
            self.assertEqual(result.json()["status"], "saved")
            attachment = parent.attachments.get()
            self.assertEqual(attachment.organization, self.center)
            self.assertIsNone(attachment.document_date)
            self.assertIsNone(attachment.case_id)
            self.assertEqual(attachment.visibility, "audit_only")
        self.assertEqual(report.document_date.isoformat(), "2016-05-12")
        for model in (AuditCase, Response, DeadlineExtension):
            self.assertFalse(model.objects.exists())
        self.assertEqual(ActivityLog.objects.filter(actor=self.auditor).count(), 4)

    def test_retries_and_renamed_duplicates_preserve_existing_metadata_and_file(self):
        report = self.report()
        path = report.file.name
        result = self.client.post(self.url, self.data(title="No reemplazar", visibility="institution",
            file=SimpleUploadedFile("renombrado.pdf", b"%PDF-1.4\noriginal")))
        self.assertEqual(result.json()["status"], "duplicate")
        self.assertEqual(result.json()["report_id"], report.pk)
        report.refresh_from_db()
        self.assertEqual(report.title, "Informe original")
        self.assertEqual(report.visibility, "audit_only")
        self.assertEqual(report.file.name, path)
        for _ in range(2):
            result = self.client.post(self.url, self.data("anexo", document_type="other", parent_report=report.pk))
            self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "duplicate")
        self.assertEqual(report.attachments.count(), 1)
        result = self.client.post(self.url, self.data(document_type="other", parent_report=report.pk))
        self.assertEqual(result.json()["status"], "duplicate")
        self.assertEqual(AuditDocument.objects.count(), 2)
        self.assertEqual(ActivityLog.objects.count(), 2)
        self.assertEqual(len([p for p in self.storage.rglob("*") if p.is_file()]), 2)

    def test_parent_from_another_center_or_a_child_cannot_be_used(self):
        parent = self.report(url=reverse("historical_bulk_file", args=[self.other.pk]))
        result = self.client.post(self.url, self.data("anexo", document_type="other", parent_report=parent.pk))
        self.assertEqual(result.status_code, 400)
        own = self.report("propio")
        result = self.client.post(self.url, self.data("anexo", document_type="other", parent_report=own.pk))
        child_id = result.json()["document_id"]
        result = self.client.post(self.url, self.data("anexo2", document_type="other", parent_report=child_id))
        self.assertEqual(result.status_code, 400)
        self.assertEqual(AuditDocument.objects.count(), 3)
        page = self.client.get(self.page, {"report": parent.pk})
        self.assertEqual(page.context["bulk_config"]["selectedReport"], "")
        self.assertNotIn(parent.pk, [r["id"] for r in page.context["bulk_config"]["reports"]])

    def test_bad_file_does_not_undo_successes_and_can_be_retried(self):
        parent = self.report()
        bad = self.client.post(self.url, self.data("bad", document_type="other", parent_report=parent.pk,
            file=SimpleUploadedFile("falso.pdf", b"not pdf")))
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(AuditDocument.objects.filter(pk=parent.pk).exists())
        good = self.client.post(self.url, self.data("correcto", document_type="other", parent_report=parent.pk))
        self.assertEqual(good.json()["status"], "saved")
        self.assertEqual(parent.attachments.count(), 1)

    def test_invalid_metadata_parent_and_formats_are_rejected(self):
        for changes in ({"document_type": "report"}, {"document_type": "other"},
                        {"visibility": "public"}, {"document_date": "2019-02-31"},
                        {"title": "x" * 301}, {"reference": "x" * 81}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post(self.url, self.data(**changes)).status_code, 400)
        self.assertEqual(self.client.post(self.url, self.data(file=SimpleUploadedFile("image.png", b"\x89PNG\r\n\x1a\nbody"))).status_code, 400)
        with override_settings(FILE_MAX_UPLOAD_MB=0):
            self.assertEqual(self.client.post(self.url, self.data()).status_code, 400)
        self.assertFalse(AuditDocument.objects.exists())

    def test_csrf_and_one_file_per_request_are_required(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.auditor)
        self.assertEqual(strict.post(self.url, self.data()).status_code, 403)
        strict.get(self.page)
        payload = self.data(csrfmiddlewaretoken=strict.cookies["csrftoken"].value)
        self.assertEqual(strict.post(self.url, payload).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url, self.data(file=[SimpleUploadedFile("a.pdf", b"%PDF-a"), SimpleUploadedFile("b.pdf", b"%PDF-b")])).status_code, 400)

    def test_failed_storage_rolls_back_only_the_current_file(self):
        report = self.report()
        with patch("apps.audits.historical_documents.ActivityLog.objects.create", side_effect=OSError("disk")):
            result = self.client.post(self.url, self.data("anexo", document_type="other", parent_report=report.pk))
        self.assertEqual(result.status_code, 503)
        self.assertEqual(AuditDocument.objects.count(), 1)
        self.assertEqual(len([p for p in self.storage.rglob("*") if p.is_file()]), 1)

    def test_shared_child_stays_private_until_parent_is_shared(self):
        parent = self.report()
        response = self.client.post(self.url, self.data("anexo", document_type="other", parent_report=parent.pk, visibility="institution"))
        child_id = response.json()["document_id"]
        self.client.force_login(self.institution)
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[child_id])).status_code, 403)
        parent.visibility = "institution"
        parent.save(update_fields=["visibility"])
        response = self.client.get(reverse("download_audit_document", args=[child_id]))
        self.assertEqual(response.status_code, 200)
        response.close()
