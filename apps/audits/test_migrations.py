import tempfile

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings


class RetireCaseReportFileMigrationTests(TransactionTestCase):
    """0010 conserva cada informe PDF heredado como documento antes de quitar el campo."""

    before = [("audits", "0009_auditinquiry_auditinquirymessage_and_more")]
    after = [("audits", "0010_retire_case_report_file")]

    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        media = override_settings(MEDIA_ROOT=storage.name)
        media.enable()
        self.addCleanup(media.disable)

        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        self.addCleanup(self._migrate_to_latest)
        old_apps = executor.loader.project_state(self.before).apps
        Organization = old_apps.get_model("institutions", "Organization")
        User = old_apps.get_model("accounts", "User")
        AuditCase = old_apps.get_model("audits", "AuditCase")
        AuditDocument = old_apps.get_model("audits", "AuditDocument")

        center = Organization.objects.create(code="CE-MIG", name="Centro", kind="educational_center")
        auditor = User.objects.create(username="auditor.mig", role="auditor")

        def legacy_case(reference, status):
            name = default_storage.save(f"legacy/{reference}.pdf", ContentFile(b"%PDF-1.4\nheredado"))
            return AuditCase.objects.create(
                reference=reference, title=f"Expediente {reference}", audited_organization=center,
                status=status, assigned_auditor=auditor, created_by=auditor, report_file=name,
            )

        self.without_report = legacy_case("IA-MIG-1", "sent")
        self.with_report = legacy_case("IA-MIG-2", "sent")
        AuditDocument.objects.create(
            case=self.with_report, organization=center, document_type="report", title="Informe",
            version=2, status="approved", visibility="institution", file="reports/vigente.docx",
            original_filename="vigente.docx", sha256="abc",
        )
        self.already_registered = legacy_case("IA-MIG-3", "sent")
        AuditDocument.objects.create(
            case=self.already_registered, organization=center, document_type="report",
            title="Migrado", version=1, status="approved", visibility="institution",
            file=self.already_registered.report_file.name, original_filename="IA-MIG-3.pdf", sha256="",
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        self.Document = executor.loader.project_state(self.after).apps.get_model("audits", "AuditDocument")

    def _migrate_to_latest(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_case_without_report_gets_version_one(self):
        document = self.Document.objects.get(case_id=self.without_report.pk)
        self.assertEqual(document.document_type, "report")
        self.assertEqual(document.version, 1)
        self.assertEqual(document.status, "approved")
        self.assertEqual(document.visibility, "institution")
        self.assertEqual(document.file.name, self.without_report.report_file.name)
        self.assertEqual(document.size, len(b"%PDF-1.4\nheredado"))
        self.assertEqual(len(document.sha256), 64)

    def test_existing_report_versions_stay_current(self):
        documents = self.Document.objects.filter(case_id=self.with_report.pk)
        self.assertEqual(documents.filter(document_type="report").get().version, 2)
        legacy = documents.get(document_type="other")
        self.assertEqual(legacy.status, "historical")
        self.assertEqual(legacy.visibility, "audit_only")
        self.assertEqual(legacy.file.name, self.with_report.report_file.name)

    def test_already_registered_file_is_not_duplicated(self):
        self.assertEqual(self.Document.objects.filter(case_id=self.already_registered.pk).count(), 1)
