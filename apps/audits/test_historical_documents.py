import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.institutions.models import Organization
from .historical_documents import save_historical_bundle
from .models import (ActivityLog, AuditCase, AuditDocument, DeadlineExtension,
                     Finding, Recommendation, Response)


class HistoricalDocumentsByCenterTests(TransactionTestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        self.addCleanup(self.storage.cleanup)
        settings_override = override_settings(MEDIA_ROOT=self.storage.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.center = Organization.objects.create(code="00123", name="Centro sin cuenta", kind="educational_center")
        self.other_center = Organization.objects.create(code="00456", name="Otro centro", kind="educational_center")
        self.director = User.objects.create_user(username="directora", role="audit_manager", must_change_password=False)
        self.auditor = User.objects.create_user(username="auditor", role="auditor", must_change_password=False)
        self.client.force_login(self.director)
        self.create_url = reverse("center_historical_document_create", args=[self.center.pk])

    def pdf(self, name="informe.pdf", text="original"):
        return SimpleUploadedFile(name, f"%PDF-1.4\n{text}".encode(), content_type="application/pdf")

    def payload(self, attachments=0):
        data = {"organization": self.other_center.pk, "reference": "IA-2018-001",
                "title": "Informe anterior de 2018", "document_date": "2018-04-23",
                "visibility": "institution", "file": self.pdf(),
                "attachments-TOTAL_FORMS": str(attachments), "attachments-INITIAL_FORMS": "0"}
        for index in range(attachments):
            data.update({f"attachments-{index}-document_type": "historical_response",
                f"attachments-{index}-title": f"Respuesta {index}",
                f"attachments-{index}-reference": f"RESP-{index}",
                f"attachments-{index}-document_date": "2018-06-01",
                f"attachments-{index}-visibility": "audit_only" if index else "institution",
                f"attachments-{index}-file": self.pdf(f"respuesta{index}.pdf", f"respuesta {index}")})
        return data

    def create_report(self, count=0):
        response = self.client.post(self.create_url, self.payload(count))
        self.assertEqual(response.status_code, 302, response.content[:1000])
        return AuditDocument.objects.get(document_type="historical_report")

    def test_center_is_fixed_and_archiving_does_not_create_accounts_or_deadlines(self):
        form = self.client.get(self.create_url)
        self.assertContains(form, "Centro sin cuenta")
        self.assertTrue(form.context["form"].fields["organization"].disabled)
        profile = self.client.get(reverse("director_educational_center_detail", args=[self.center.pk]))
        self.assertContains(profile, self.create_url)
        report = self.create_report(2)
        self.assertEqual(report.organization, self.center)
        self.assertEqual(report.document_date, date(2018, 4, 23))
        self.assertEqual(report.status, "historical")
        self.assertIsNone(report.case_id)
        self.assertEqual(report.file.read(), b"%PDF-1.4\noriginal")
        report.file.close()
        self.assertEqual(report.attachments.count(), 2)
        for item in report.attachments.all():
            self.assertEqual(item.organization, self.center)
            self.assertEqual(item.document_date, date(2018, 6, 1))
            self.assertEqual(item.status, "historical")
            self.assertIsNone(item.case_id)
        self.assertFalse(User.objects.filter(organization=self.center).exists())
        for model in (AuditCase, Finding, Recommendation, Response, DeadlineExtension):
            self.assertFalse(model.objects.exists())
        self.assertEqual(ActivityLog.objects.filter(action="historical_document_uploaded").count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action="historical_attachment_uploaded").count(), 2)

    def test_missing_original_date_is_not_replaced_with_upload_date(self):
        data = self.payload()
        data["document_date"] = ""
        self.client.post(self.create_url, data)
        self.assertIsNone(AuditDocument.objects.get().document_date)

    def test_more_documents_can_be_added_without_replacing_the_original(self):
        report = self.create_report()
        original_path = report.file.name
        original_uploaded_at = report.uploaded_at
        data = self.payload(2)
        self.assertRedirects(self.client.post(reverse("historical_attachment_create", args=[report.pk]), data),
                             reverse("historical_document_detail", args=[report.pk]))
        report.refresh_from_db()
        self.assertEqual(report.file.name, original_path)
        self.assertEqual(report.uploaded_at, original_uploaded_at)
        self.assertEqual(report.attachments.count(), 2)

    def test_duplicate_report_and_duplicate_attachments_are_rejected_before_writes(self):
        report = self.create_report(1)
        response = self.client.post(self.create_url, self.payload())
        self.assertContains(response, "ya está registrado")
        duplicate = self.client.post(reverse("historical_attachment_create", args=[report.pk]), self.payload(1))
        self.assertContains(duplicate, "está repetido")
        self.assertEqual(AuditDocument.objects.count(), 2)
        self.assertEqual(len([p for p in Path(self.storage.name).rglob("*") if p.is_file()]), 2)

    def test_duplicate_within_new_batch_does_not_save_any_files(self):
        data = self.payload(2)
        data["attachments-1-file"] = self.pdf("otro-nombre.pdf", "respuesta 0")
        self.assertContains(self.client.post(self.create_url, data), "está repetido")
        self.assertFalse(AuditDocument.objects.exists())
        self.assertFalse(ActivityLog.objects.exists())
        self.assertFalse(any(Path(self.storage.name).rglob("*.pdf")))

    def test_invalid_file_invalid_type_and_too_many_rows_do_not_save(self):
        data = self.payload(1)
        data["attachments-0-file"] = SimpleUploadedFile("falso.pdf", b"not a pdf")
        self.assertContains(self.client.post(self.create_url, data), "PDF válido")
        data = self.payload(1)
        data["attachments-0-document_type"] = "report"
        self.assertEqual(self.client.post(self.create_url, data).status_code, 200)
        data = self.payload(0)
        data["attachments-TOTAL_FORMS"] = "50000"
        response = self.client.post(self.create_url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["attachments"].forms), 10)
        self.assertFalse(AuditDocument.objects.exists())

    def test_empty_optional_rows_are_accepted_but_add_document_requires_a_file(self):
        data = self.payload()
        data["attachments-TOTAL_FORMS"] = "2"
        for i in range(2):
            data[f"attachments-{i}-document_type"] = "other"
            data[f"attachments-{i}-visibility"] = "audit_only"
        self.assertEqual(self.client.post(self.create_url, data).status_code, 302)
        report = AuditDocument.objects.get()
        response = self.client.post(reverse("historical_attachment_create", args=[report.pk]), data)
        self.assertContains(response, "al menos un documento")

    def test_institutions_only_see_shared_documents_from_their_own_center(self):
        report = self.create_report(2)
        shared = report.attachments.get(visibility="institution")
        private = report.attachments.get(visibility="audit_only")
        institution = User.objects.create_user(username="00123", role="institution", organization=self.center, must_change_password=False)
        self.client.force_login(institution)
        detail = self.client.get(reverse("historical_document_detail", args=[report.pk]))
        self.assertContains(detail, shared.title)
        self.assertNotContains(detail, private.title)
        self.assertNotContains(detail, "Agregar documentos")
        self.assertNotContains(detail, "Guardar visibilidad")
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[shared.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[private.pk])).status_code, 403)
        history = self.client.get(reverse("institution_history"))
        self.assertEqual(history.context["documents"].count(), 1)
        self.assertNotContains(history, private.title)
        outsider = User.objects.create_user(username="00456", role="institution", organization=self.other_center, must_change_password=False)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("historical_document_detail", args=[report.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[shared.pk])).status_code, 403)

    def test_parent_visibility_limits_attachments_and_updates_are_logged(self):
        report = self.create_report(1)
        shared = report.attachments.get()
        visibility_url = reverse("historical_document_visibility", args=[report.pk])
        self.client.post(visibility_url, {"visibility": "audit_only"})
        self.assertEqual(ActivityLog.objects.filter(action="historical_document_visibility_changed").count(), 1)
        institution = User.objects.create_user(username="00123", role="institution", organization=self.center, must_change_password=False)
        self.client.force_login(institution)
        self.assertEqual(self.client.get(reverse("download_audit_document", args=[shared.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("institution_history")), report.title)
        self.assertEqual(self.client.post(visibility_url, {"visibility": "institution"}).status_code, 403)

    def test_auditor_can_add_historical_documents_but_institution_cannot(self):
        self.client.force_login(self.auditor)
        report = self.create_report(1)
        download = self.client.get(reverse("download_audit_document", args=[report.attachments.get().pk]))
        self.assertEqual(download.status_code, 200)
        download.close()
        institution = User.objects.create_user(username="00123", role="institution", organization=self.center, must_change_password=False)
        self.client.force_login(institution)
        self.assertEqual(self.client.post(self.create_url, self.payload()).status_code, 403)
        self.assertEqual(self.client.post(reverse("historical_attachment_create", args=[report.pk]), self.payload(1)).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.create_url).status_code, 302)

    def test_failed_storage_rolls_back_records_and_removes_new_files(self):
        from django.core.files.storage import default_storage

        actual_save = default_storage.save
        calls = 0
        def fail_second_save(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("storage unavailable")
            return actual_save(*args, **kwargs)
        with patch.object(default_storage, "save", side_effect=fail_second_save):
            with self.assertRaises(OSError):
                save_historical_bundle(user=self.director,
                    report_data={"organization": self.center, "title": "Informe",
                                 "file": self.pdf(), "visibility": "audit_only"},
                    attachments=[{"file": self.pdf("anexo.pdf", "otro contenido"),
                                  "visibility": "audit_only", "document_type": "other"}])
        self.assertFalse(AuditDocument.objects.exists())
        self.assertFalse(ActivityLog.objects.exists())
        self.assertFalse(any(Path(self.storage.name).rglob("*.pdf")))

    def test_cross_center_parent_is_rejected_by_model_validation(self):
        report = self.create_report()
        child = AuditDocument(organization=self.other_center, parent_report=report,
                              document_type="other", status="historical")
        with self.assertRaises(ValidationError):
            child.clean()
