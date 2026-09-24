import hashlib
import secrets
from datetime import date, timedelta
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.base import ContentFile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from apps.accounts.models import User
from apps.institutions.models import Organization

from ...models import (
    ActivityLog,
    AuditCase,
    AuditDocument,
    CaseDecision,
    Evidence,
    Finding,
    Recommendation,
    Response,
    Review,
)


def build_demo_docx(title, paragraphs):
    """Build a small, valid Word document without adding a runtime dependency."""
    body = []
    for index, paragraph in enumerate([title, *paragraphs]):
        properties = "<w:rPr><w:b/><w:sz w:val='30'/></w:rPr>" if index == 0 else ""
        body.append(
            "<w:p><w:r>"
            f"{properties}<w:t xml:space='preserve'>{escape(paragraph)}</w:t>"
            "</w:r></w:p>"
        )
    document_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        f"<w:body>{''.join(body)}<w:sectPr/></w:body></w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
            "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
            "<Default Extension='xml' ContentType='application/xml'/>"
            "<Override PartName='/word/document.xml' "
            "ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>"
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
            "<Relationship Id='rId1' "
            "Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' "
            "Target='word/document.xml'/></Relationships>",
        )
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def build_demo_pdf(title, lines):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    text = pdf.beginText(72, 730)
    text.setFont("Helvetica-Bold", 14)
    text.textLine(title)
    text.setFont("Helvetica", 10)
    text.textLine("")
    for line in lines:
        text.textLine(line)
    pdf.drawText(text)
    pdf.save()
    return buffer.getvalue()


class Command(BaseCommand):
    help = "Crea usuarios y escenarios completos para demostrar el flujo de auditoría."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Genera y asigna nuevas contraseñas a los usuarios de demostración.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_DATA:
            raise CommandError("Los datos de demostración no se permiten en producción.")
        reset_passwords = options["reset_passwords"]
        center, _ = Organization.objects.update_or_create(
            code="10754",
            defaults={
                "email": "10754@clases.edu.sv",
                "name": "Instituto Nacional de Nahuizalco",
                "kind": Organization.Kind.EDUCATIONAL_CENTER,
                "educational_center_type": "Instituto",
                "department": "Sonsonate",
                "municipality": "Nahuizalco",
                "address": "Nahuizalco, Sonsonate",
                "is_active": True,
            },
        )
        florinda_center, _ = Organization.objects.update_or_create(
            code="10471",
            defaults={
                "email": "10471@clases.edu.sv",
                "name": "Centro Escolar Florinda B. González",
                "kind": Organization.Kind.EDUCATIONAL_CENTER,
                "educational_center_type": "Centro escolar",
                "department": "Santa Ana",
                "municipality": "Santa Ana Centro",
                "address": "Distrito de Santa Ana, Santa Ana Centro, Santa Ana",
                "is_active": True,
            },
        )
        comunidad_center, _ = Organization.objects.update_or_create(
            code="11489",
            defaults={
                "email": "11489@clases.edu.sv",
                "name": "Complejo Educativo Comunidad 10 de Octubre",
                "kind": Organization.Kind.EDUCATIONAL_CENTER,
                "educational_center_type": "Complejo educativo",
                "department": "San Salvador",
                "municipality": "San Salvador Sur",
                "address": "Distrito de San Marcos, San Salvador Sur, San Salvador",
                "is_active": True,
            },
        )
        departmental, _ = Organization.objects.update_or_create(
            code="DDE-SONSONATE",
            defaults={
                "name": "Dirección Departamental de Educación de Sonsonate",
                "kind": Organization.Kind.DEPARTMENTAL_OFFICE,
                "department": "Sonsonate",
                "is_active": True,
            },
        )
        santa_ana_departmental, _ = Organization.objects.update_or_create(
            code="DDE-SANTA-ANA",
            defaults={
                "name": "Dirección Departamental de Educación de Santa Ana",
                "kind": Organization.Kind.DEPARTMENTAL_OFFICE,
                "department": "Santa Ana",
                "is_active": True,
            },
        )
        san_salvador_departmental, _ = Organization.objects.update_or_create(
            code="DDE-SAN-SALVADOR",
            defaults={
                "name": "Dirección Departamental de Educación de San Salvador",
                "kind": Organization.Kind.DEPARTMENTAL_OFFICE,
                "department": "San Salvador",
                "is_active": True,
            },
        )
        audit_unit, _ = Organization.objects.update_or_create(
            code="DAI-MINED",
            defaults={
                "name": "Dirección de Auditoría Interna",
                "kind": Organization.Kind.MINISTRY_UNIT,
                "department": "San Salvador",
                "is_active": True,
            },
        )

        auditor, auditor_created = User.objects.update_or_create(
            username="auditor.demo",
            defaults={
                "first_name": "Sandra",
                "last_name": "Auditoría",
                "email": "auditor.demo@localhost",
                "role": User.Role.AUDITOR,
                "organization": audit_unit,
                "job_title": "Auditora",
                "is_active": True,
                "is_staff": True,
                "must_change_password": False,
            },
        )
        director, director_created = User.objects.update_or_create(
            username="directora.demo",
            defaults={
                "first_name": "Directora",
                "last_name": "de Auditoría",
                "email": "directora.demo@localhost",
                "role": User.Role.AUDIT_MANAGER,
                "organization": audit_unit,
                "job_title": "Directora de Auditoría Interna",
                "is_active": True,
                "is_staff": False,
                "must_change_password": False,
            },
        )
        if not User.objects.filter(username=center.code).exists():
            User.objects.filter(username=f"centro.{center.code}", organization=center).update(username=center.code)
        institutional, institutional_created = User.objects.update_or_create(
            username=center.code,
            defaults={
                "first_name": "Responsable",
                "last_name": "Institucional",
                "email": center.email or "10754@example.edu.sv",
                "role": User.Role.INSTITUTION,
                "organization": center,
                "job_title": "Dirección del centro educativo",
                "is_active": True,
                "is_staff": False,
                "must_change_password": False,
            },
        )
        password = self._update_demo_passwords(
            [
                (auditor, auditor_created),
                (director, director_created),
                (institutional, institutional_created),
            ],
            reset_passwords,
        )

        self._seed_published_case(center, departmental, auditor)
        self._seed_pending_publication_case(center, auditor)
        self._seed_under_review_case(center, auditor, institutional)
        self._seed_correction_case(center, auditor, institutional)
        self._seed_pending_closure_case(center, auditor, institutional)
        self._seed_florinda_case(florinda_center, santa_ana_departmental, auditor)
        self._seed_comunidad_case(
            comunidad_center,
            san_salvador_departmental,
            auditor,
        )
        auditor.assigned_organizations.add(center, florinda_center, comunidad_center)

        self.stdout.write(self.style.SUCCESS("Datos de demostración creados y actualizados."))
        self._write_credentials(
            auditor_created,
            director_created,
            institutional_created,
            reset_passwords,
            password,
        )
        self.stdout.write("Escenarios disponibles:")
        self.stdout.write("  Dirección: IA/NA-011-2026 pendiente de aprobación y IA/NA-007-2024 pendiente de cierre.")
        self.stdout.write("  Auditoría: IA/NA-009-2025 contiene una respuesta pendiente de revisión.")
        self.stdout.write("  Centro educativo: IA/NA-010-2025 admite respuesta e IA/NA-008-2025 requiere corrección.")
        self.stdout.write(
            "  Centros adicionales: IA/NA-043-2024 e IA/NA-046-2024 permiten probar activación y respuesta."
        )
        self.stdout.write("Estas credenciales y documentos son únicamente para desarrollo local.")

    def _update_demo_passwords(self, users, reset_passwords):
        users_requiring_password = [
            user for user, created in users if created or reset_passwords
        ]
        if not users_requiring_password:
            return None
        password = secrets.token_urlsafe(14)
        for user in users_requiring_password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return password

    def _write_credentials(
        self,
        auditor_created,
        director_created,
        institutional_created,
        reset_passwords,
        password,
    ):
        credentials = [
            ("Auditoría", "auditor.demo", auditor_created),
            ("Dirección", "directora.demo", director_created),
            ("Centro educativo", "10754", institutional_created),
        ]
        for label, username, created in credentials:
            if created or reset_passwords:
                self.stdout.write(f"{label}: {username} / {password}")
            else:
                self.stdout.write(f"{label}: se conservó la contraseña existente de {username}.")
        if password is None:
            self.stdout.write(
                "Para generar nuevas credenciales de forma explícita, use seed_demo --reset-passwords."
            )

    def _upsert_case(self, reference, **defaults):
        case, _ = AuditCase.objects.update_or_create(reference=reference, defaults=defaults)
        return case

    def _upsert_finding(self, case, number, **defaults):
        finding, _ = Finding.objects.update_or_create(
            case=case,
            number=number,
            defaults=defaults,
        )
        return finding

    def _upsert_recommendation(self, finding, number, **defaults):
        recommendation, _ = Recommendation.objects.update_or_create(
            finding=finding,
            number=number,
            defaults=defaults,
        )
        return recommendation

    def _upsert_report_document(
        self,
        case,
        auditor,
        *,
        reference,
        title,
        status,
        visibility,
        paragraphs,
    ):
        payload = build_demo_docx(title, paragraphs)
        document, _ = AuditDocument.objects.get_or_create(
            case=case,
            document_type=AuditDocument.DocumentType.REPORT,
            version=1,
            defaults={
                "organization": case.audited_organization,
                "reference": reference,
                "title": title,
                "document_date": case.report_date,
                "status": status,
                "visibility": visibility,
                "original_filename": f"{reference.lower().replace('/', '-')}.docx",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "uploaded_by": auditor,
            },
        )
        document.organization = case.audited_organization
        document.reference = reference
        document.title = title
        document.document_date = case.report_date
        document.status = status
        document.visibility = visibility
        document.original_filename = f"{reference.lower().replace('/', '-')}.docx"
        document.size = len(payload)
        document.sha256 = hashlib.sha256(payload).hexdigest()
        document.uploaded_by = auditor
        if not document.file or not document.file.storage.exists(document.file.name):
            document.file.save(document.original_filename, ContentFile(payload), save=False)
        document.save()
        return document

    def _upsert_response(self, recommendation, institutional, version=1, **defaults):
        response, _ = Response.objects.update_or_create(
            recommendation=recommendation,
            version=version,
            defaults={"submitted_by": institutional, **defaults},
        )
        return response

    def _upsert_pending_response(self, recommendation, institutional, **defaults):
        response = (
            recommendation.responses.filter(review__isnull=True)
            .order_by("-version")
            .first()
        )
        if response is None:
            latest_response = recommendation.responses.order_by("-version").first()
            response = Response(
                recommendation=recommendation,
                version=(latest_response.version + 1 if latest_response else 1),
            )
        for field, value in {"submitted_by": institutional, **defaults}.items():
            setattr(response, field, value)
        response.save()
        return response

    def _upsert_evidence(self, response, institutional, *, filename, title, lines, category):
        payload = build_demo_pdf(title, lines)
        evidence, _ = Evidence.objects.get_or_create(
            response=response,
            original_filename=filename,
            defaults={
                "category": category,
                "description": title,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "scan_status": Evidence.ScanStatus.CLEAN,
                "uploaded_by": institutional,
            },
        )
        evidence.category = category
        evidence.description = title
        evidence.size = len(payload)
        evidence.sha256 = hashlib.sha256(payload).hexdigest()
        evidence.scan_status = Evidence.ScanStatus.CLEAN
        evidence.uploaded_by = institutional
        if not evidence.file or not evidence.file.storage.exists(evidence.file.name):
            evidence.file.save(filename, ContentFile(payload), save=False)
        evidence.save()
        return evidence

    def _upsert_review(self, response, auditor, *, outcome, comments):
        review, _ = Review.objects.update_or_create(
            response=response,
            defaults={
                "outcome": outcome,
                "comments": comments,
                "reviewed_by": auditor,
            },
        )
        return review

    def _upsert_pending_decision(self, case, auditor, *, kind, document=None, note):
        decision = CaseDecision.objects.filter(
            case=case,
            status=CaseDecision.Status.PENDING,
        ).first()
        if decision is None:
            decision = CaseDecision(case=case, status=CaseDecision.Status.PENDING)
        decision.document = document
        decision.kind = kind
        decision.request_note = note
        decision.previous_case_status = (
            AuditCase.Status.DRAFT
            if kind == CaseDecision.Kind.PUBLICATION
            else AuditCase.Status.UNDER_REVIEW
        )
        decision.requested_by = auditor
        decision.decision_note = ""
        decision.decided_by = None
        decision.decided_at = None
        decision.save()
        return decision

    def _upsert_activity(self, case, actor, action, target, details):
        ActivityLog.objects.update_or_create(
            case=case,
            action=action,
            target_type=target.__class__.__name__,
            target_id=str(target.pk),
            defaults={"actor": actor, "details": details},
        )

    def _seed_reference_case(
        self,
        *,
        reference,
        title,
        center,
        auditor,
        report_date,
        period_start,
        period_end,
        period_description,
        findings,
    ):
        today = date.today()
        previous_case_status = (
            AuditCase.objects.filter(reference=reference)
            .values_list("status", flat=True)
            .first()
        )
        case = self._upsert_case(
            reference,
            title=title,
            audited_organization=center,
            report_date=report_date,
            period_start=period_start,
            period_end=period_end,
            response_deadline=today + timedelta(days=15),
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        if previous_case_status and previous_case_status != AuditCase.Status.PUBLISHED:
            case.status = previous_case_status
            case.save(update_fields=["status", "updated_at"])

        self._upsert_report_document(
            case,
            auditor,
            reference=reference,
            title=title,
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            paragraphs=[
                f"Centro educativo: {center.name}, código de infraestructura {center.code}.",
                f"Período examinado: {period_description}.",
                f"Fecha del informe final: {report_date:%d/%m/%Y}.",
                (
                    "Para la demostración se estructuró una selección de "
                    f"{len(findings)} hallazgos representativos del informe final."
                ),
            ],
        )

        for finding_data in findings:
            finding = self._upsert_finding(
                case,
                finding_data["number"],
                title=finding_data["title"],
                risk_level=finding_data["risk_level"],
                condition=finding_data["condition"],
                criteria=finding_data["criteria"],
                cause=finding_data["cause"],
                effect=finding_data["effect"],
            )
            existing_recommendation = finding.recommendations.filter(number=1).first()
            previous_recommendation_status = (
                existing_recommendation.status if existing_recommendation else None
            )
            recommendation = self._upsert_recommendation(
                finding,
                1,
                text=finding_data["recommendation"],
                responsible_organization=finding_data.get("responsible", center),
                deadline=today + timedelta(days=15),
                evidence_requirements=finding_data["evidence_requirements"],
                status=Recommendation.Status.PENDING,
            )
            if (
                previous_recommendation_status
                and previous_recommendation_status != Recommendation.Status.PENDING
            ):
                recommendation.status = previous_recommendation_status
                recommendation.save(update_fields=["status"])
        return case

    def _seed_florinda_case(self, center, departmental, auditor):
        self._seed_reference_case(
            reference="IA/NA-043-2024",
            title=(
                "Examen especial a los aspectos administrativos, operativos, financieros "
                "y legales del Centro Escolar Florinda B. González"
            ),
            center=center,
            auditor=auditor,
            report_date=date(2025, 2, 25),
            period_start=date(2023, 1, 1),
            period_end=date(2024, 10, 31),
            period_description="enero de 2023 a octubre de 2024",
            findings=[
                {
                    "number": 1,
                    "title": (
                        "Debilidades de control interno que requieren la implementación "
                        "de acciones de mejora"
                    ),
                    "risk_level": Finding.RiskLevel.HIGH,
                    "condition": (
                        "El informe identificó debilidades administrativas y de control interno "
                        "en la gestión del centro educativo."
                    ),
                    "criteria": (
                        "El Consejo Directivo Escolar debe administrar los recursos y documentar "
                        "sus actuaciones conforme a la normativa institucional aplicable."
                    ),
                    "cause": (
                        "Aplicación incompleta de los controles y de las responsabilidades "
                        "asignadas al organismo de administración escolar."
                    ),
                    "effect": (
                        "Riesgo de operaciones no verificables y de incumplimientos administrativos."
                    ),
                    "recommendation": (
                        "Implemente y documente un plan de acciones correctivas para las debilidades "
                        "de control interno comunicadas en el informe."
                    ),
                    "evidence_requirements": (
                        "Plan de mejora aprobado.\nActa del Consejo Directivo Escolar.\n"
                        "Documentos que acrediten la ejecución de cada acción."
                    ),
                },
                {
                    "number": 4,
                    "title": (
                        "Liquidación extemporánea de fondos del Estado por US$7,390.27, "
                        "correspondiente al año 2023"
                    ),
                    "risk_level": Finding.RiskLevel.HIGH,
                    "condition": (
                        "Los fondos estatales del año 2023 por US$7,390.27 fueron liquidados "
                        "fuera del plazo establecido."
                    ),
                    "criteria": (
                        "Los fondos transferidos deben liquidarse dentro de los plazos y con los "
                        "documentos exigidos por la normativa financiera."
                    ),
                    "cause": "Falta de seguimiento oportuno al calendario de liquidaciones.",
                    "effect": (
                        "Retraso en la rendición de cuentas y riesgo de observaciones sobre el uso "
                        "de los fondos públicos."
                    ),
                    "recommendation": (
                        "Establezca controles de vencimiento y responsables para presentar las "
                        "liquidaciones de fondos estatales dentro de los plazos aplicables."
                    ),
                    "evidence_requirements": (
                        "Calendario de liquidaciones.\nConstancia de responsable designado.\n"
                        "Comprobantes de liquidación y seguimiento."
                    ),
                },
                {
                    "number": 7,
                    "title": (
                        "Falta de documentación de respaldo y gastos no elegibles ejecutados "
                        "con fondos de otros ingresos"
                    ),
                    "risk_level": Finding.RiskLevel.CRITICAL,
                    "condition": (
                        "Se identificaron gastos sin documentación suficiente y gastos no elegibles "
                        "correspondientes a los años 2023 y 2024."
                    ),
                    "criteria": (
                        "Todo gasto debe ser elegible, autorizado y respaldado con documentación "
                        "legal que permita verificar su finalidad y pago."
                    ),
                    "cause": (
                        "Controles insuficientes en la autorización, archivo y revisión de los gastos."
                    ),
                    "effect": (
                        "El informe determinó reintegros por gastos no documentados y no elegibles."
                    ),
                    "recommendation": (
                        "Complete los respaldos, efectúe los reintegros señalados en el informe y "
                        "aplique una revisión previa de elegibilidad para cada gasto."
                    ),
                    "evidence_requirements": (
                        "Comprobantes de reintegro.\nExpedientes de gasto completos.\n"
                        "Lista de control de elegibilidad aprobada."
                    ),
                },
                {
                    "number": 10,
                    "title": (
                        "Inadecuada administración de bienes muebles y recursos tecnológicos, "
                        "y falta de un plan de descarte"
                    ),
                    "risk_level": Finding.RiskLevel.HIGH,
                    "condition": (
                        "El centro mantenía bienes sin controles suficientes y no contaba con un "
                        "plan documentado para descartar mobiliario y equipo deteriorado o en desuso."
                    ),
                    "criteria": (
                        "Los bienes institucionales deben identificarse, custodiarse, inventariarse "
                        "y descargarse conforme a los procedimientos autorizados."
                    ),
                    "cause": "Ausencia de conciliación periódica y de planificación para el descarte.",
                    "effect": (
                        "Riesgo de pérdida, deterioro y presentación inexacta del inventario institucional."
                    ),
                    "recommendation": (
                        "Actualice y concilie el inventario, fortalezca la custodia de los bienes y "
                        "prepare el plan de descarte del mobiliario y equipo en desuso."
                    ),
                    "evidence_requirements": (
                        "Inventario conciliado.\nActas de asignación y custodia.\n"
                        "Plan y acta de descarte autorizados."
                    ),
                },
            ],
        )

    def _seed_comunidad_case(self, center, departmental, auditor):
        self._seed_reference_case(
            reference="IA/NA-046-2024",
            title=(
                "Examen especial a los aspectos administrativos, operativos, financieros "
                "y legales del Complejo Educativo Comunidad 10 de Octubre"
            ),
            center=center,
            auditor=auditor,
            report_date=date(2025, 4, 1),
            period_start=date(2023, 1, 1),
            period_end=date(2024, 12, 31),
            period_description="enero de 2023 a diciembre de 2024",
            findings=[
                {
                    "number": 1,
                    "title": (
                        "Debilidades de control interno que requieren la implementación "
                        "de acciones de mejora"
                    ),
                    "risk_level": Finding.RiskLevel.HIGH,
                    "condition": (
                        "El informe identificó debilidades en la administración, documentación "
                        "y control de los recursos del complejo educativo."
                    ),
                    "criteria": (
                        "El organismo de administración escolar debe aplicar controles que aseguren "
                        "la legalidad, trazabilidad y resguardo de sus operaciones."
                    ),
                    "cause": (
                        "Supervisión insuficiente y aplicación desigual de los controles internos."
                    ),
                    "effect": (
                        "Riesgo de errores, incumplimientos y operaciones sin respaldo verificable."
                    ),
                    "recommendation": (
                        "Apruebe, ejecute y supervise un plan de mejora para atender las debilidades "
                        "de control interno detalladas en el informe."
                    ),
                    "evidence_requirements": (
                        "Plan de mejora.\nActa de aprobación.\nInformes de seguimiento y anexos."
                    ),
                },
                {
                    "number": 4,
                    "title": (
                        "Falta de liquidación de fondos del Estado por US$14,329.92, "
                        "correspondiente al año 2024"
                    ),
                    "risk_level": Finding.RiskLevel.CRITICAL,
                    "condition": (
                        "A la fecha del informe no se habían liquidado fondos estatales del año 2024 "
                        "por US$14,329.92."
                    ),
                    "criteria": (
                        "Los fondos transferidos por el Ministerio deben liquidarse dentro del plazo "
                        "y mediante el sistema y documentos autorizados."
                    ),
                    "cause": (
                        "Falta de seguimiento y cierre oportuno del proceso de liquidación."
                    ),
                    "effect": (
                        "Incumplimiento del plazo de rendición de cuentas y riesgo de restricciones "
                        "en futuras transferencias."
                    ),
                    "recommendation": (
                        "Complete la liquidación pendiente y establezca controles de seguimiento "
                        "para que las transferencias futuras se liquiden oportunamente."
                    ),
                    "evidence_requirements": (
                        "Constancia de liquidación.\nDocumentación financiera de respaldo.\n"
                        "Calendario y control de vencimientos."
                    ),
                },
                {
                    "number": 5,
                    "title": (
                        "Incumplimiento al proceso de liquidación administrativa de paquetes "
                        "escolares de los años 2023 y 2024"
                    ),
                    "risk_level": Finding.RiskLevel.HIGH,
                    "condition": (
                        "Se identificaron incumplimientos en la preparación y presentación de las "
                        "liquidaciones administrativas de paquetes escolares."
                    ),
                    "criteria": (
                        "Las liquidaciones de paquetes escolares deben presentarse completas, "
                        "conciliadas y dentro de los plazos institucionales."
                    ),
                    "cause": (
                        "Controles insuficientes sobre la integración y revisión de los expedientes."
                    ),
                    "effect": (
                        "Demora en el cierre administrativo y riesgo de información financiera inexacta."
                    ),
                    "recommendation": (
                        "Complete, concilie y revise los expedientes de liquidación de paquetes "
                        "escolares antes de su presentación."
                    ),
                    "evidence_requirements": (
                        "Expedientes de liquidación completos.\nConciliaciones firmadas.\n"
                        "Lista de revisión previa."
                    ),
                },
                {
                    "number": 6,
                    "title": "Secciones con baja matrícula correspondientes al año 2024",
                    "risk_level": Finding.RiskLevel.MEDIUM,
                    "condition": (
                        "El informe identificó secciones con matrícula inferior a los parámetros "
                        "considerados para la organización de la planta docente."
                    ),
                    "criteria": (
                        "La planta docente y la organización de secciones deben ajustarse a la "
                        "matrícula y a la normativa técnica y legal aplicable."
                    ),
                    "cause": (
                        "La distribución de la planta docente no fue actualizada oportunamente "
                        "con base en la matrícula registrada."
                    ),
                    "effect": (
                        "Riesgo de uso ineficiente del recurso docente y de una oferta educativa "
                        "desalineada con la demanda."
                    ),
                    "recommendation": (
                        "Apoye al complejo educativo en la elaboración y reestructuración de la "
                        "planta docente, bajo la supervisión de los gestores asignados."
                    ),
                    "responsible": departmental,
                    "evidence_requirements": (
                        "Planta docente reestructurada.\nInforme de supervisión de gestores.\n"
                        "Matrícula y distribución de secciones actualizadas."
                    ),
                },
            ],
        )

    def _seed_published_case(self, center, departmental, auditor):
        today = date.today()
        case = self._upsert_case(
            "IA/NA-010-2025",
            title="Examen especial a los otros ingresos del Instituto Nacional de Nahuizalco",
            audited_organization=center,
            report_date=date(2025, 10, 11),
            period_start=date(2020, 1, 1),
            period_end=date(2025, 3, 31),
            response_deadline=today + timedelta(days=10),
            status=AuditCase.Status.PUBLISHED,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        self._upsert_report_document(
            case,
            auditor,
            reference="INF-010-2025",
            title="Informe sobre otros ingresos",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            paragraphs=[
                "Objetivo: evaluar el registro, depósito y uso de los otros ingresos.",
                "Período examinado: del 1 de enero de 2020 al 31 de marzo de 2025.",
                "El informe contiene un hallazgo y tres recomendaciones sujetas a seguimiento.",
            ],
        )
        finding = self._upsert_finding(
            case,
            1,
            title="Debilidades en los controles de los otros ingresos",
            risk_level=Finding.RiskLevel.HIGH,
            condition=(
                "Se identificaron operaciones de ingresos y gastos que no fueron registradas "
                "oportunamente en los libros autorizados y carecen de documentación suficiente."
            ),
            criteria=(
                "Los fondos administrados por el centro deben registrarse, depositarse y "
                "documentarse conforme a los lineamientos financieros institucionales."
            ),
            cause="Falta de aplicación de los controles administrativos y financieros establecidos.",
            effect="Riesgo de falta de transparencia y de información financiera no verificable.",
        )
        first_recommendation = self._upsert_recommendation(
            finding,
            1,
            text=(
                "Asegure la implementación de controles, registrando las operaciones de ingresos "
                "y gastos en los libros respectivos y documentando oportunamente los gastos ejecutados."
            ),
            responsible_organization=center,
            deadline=today + timedelta(days=10),
            evidence_requirements=(
                "Acta del Consejo Directivo Escolar.\n"
                "Copia de los registros actualizados.\n"
                "Recibos, facturas o documentación de respaldo."
            ),
            status=Recommendation.Status.PENDING,
        )
        if first_recommendation.responses.exists():
            first_recommendation.status = Recommendation.Status.SUBMITTED
            first_recommendation.save(update_fields=["status"])
            case.status = AuditCase.Status.UNDER_REVIEW
            case.save(update_fields=["status", "updated_at"])
        self._upsert_recommendation(
            finding,
            2,
            text=(
                "Documente las acciones de monitoreo y supervisión implementadas en los centros "
                "educativos respecto a la administración de los otros ingresos."
            ),
            responsible_organization=departmental,
            deadline=today + timedelta(days=10),
            evidence_requirements="Informe de monitoreo, actas de visita y plan de seguimiento.",
            status=Recommendation.Status.PENDING,
        )
        self._upsert_recommendation(
            finding,
            3,
            text=(
                "Deposite íntegramente los fondos de otros ingresos en la cuenta bancaria "
                "correspondiente y elabore las conciliaciones bancarias mensuales."
            ),
            responsible_organization=center,
            deadline=today + timedelta(days=10),
            evidence_requirements=(
                "Comprobantes de depósito.\n"
                "Estado de cuenta bancario.\n"
                "Conciliación bancaria firmada."
            ),
            status=Recommendation.Status.PENDING,
        )

    def _seed_pending_publication_case(self, center, auditor):
        today = date.today()
        case = self._upsert_case(
            "IA/NA-011-2026",
            title="Examen especial al proceso de compras y control de inventario",
            audited_organization=center,
            report_date=today - timedelta(days=7),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            response_deadline=today + timedelta(days=15),
            status=AuditCase.Status.PENDING_PUBLICATION,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        report = self._upsert_report_document(
            case,
            auditor,
            reference="INF-011-2026",
            title="Informe para aprobación: compras e inventario",
            status=AuditDocument.Status.PENDING_APPROVAL,
            visibility=AuditDocument.Visibility.AUDIT_ONLY,
            paragraphs=[
                "Objetivo: verificar la autorización, documentación y recepción de las compras.",
                "Alcance: operaciones realizadas entre enero y diciembre de 2025.",
                "Conclusión: se identificaron oportunidades de mejora en expedientes de compra e inventarios.",
                "La versión 1 se remite a la Dirección de Auditoría para autorización de publicación.",
            ],
        )
        purchase_finding = self._upsert_finding(
            case,
            1,
            title="Expedientes de compra con documentación incompleta",
            risk_level=Finding.RiskLevel.CRITICAL,
            condition=(
                "En cuatro adquisiciones no constaba la comparación de ofertas, la autorización "
                "del Consejo Directivo Escolar o la constancia de recepción de los bienes."
            ),
            criteria=(
                "Cada adquisición debe conservar evidencia de autorización, selección del proveedor, "
                "recepción y pago para permitir su trazabilidad."
            ),
            cause="El centro no utiliza una lista de control uniforme para conformar los expedientes.",
            effect="Existe riesgo de compras no justificadas y de bienes pagados sin recepción verificable.",
        )
        self._upsert_recommendation(
            purchase_finding,
            1,
            text=(
                "Implemente una lista de control obligatoria para cada expediente de compra y complete "
                "los respaldos faltantes de las adquisiciones observadas."
            ),
            responsible_organization=center,
            deadline=today + timedelta(days=15),
            evidence_requirements=(
                "Lista de control aprobada.\nExpedientes de las cuatro adquisiciones observadas.\n"
                "Acta de aprobación del Consejo Directivo Escolar."
            ),
            status=Recommendation.Status.PENDING,
        )
        inventory_finding = self._upsert_finding(
            case,
            2,
            title="Bienes sin código y conciliación de inventario",
            risk_level=Finding.RiskLevel.HIGH,
            condition=(
                "La inspección física identificó equipo sin código institucional y diferencias entre "
                "el inventario auxiliar y los bienes localizados."
            ),
            criteria="El inventario debe identificar, ubicar y conciliar periódicamente todos los bienes.",
            cause="No se asignó una persona responsable de actualizar el inventario después de cada compra.",
            effect="Los bienes pueden extraviarse o presentarse información patrimonial inexacta.",
        )
        self._upsert_recommendation(
            inventory_finding,
            1,
            text=(
                "Codifique los bienes observados, concilie el inventario físico con el registro auxiliar "
                "y asigne formalmente a la persona responsable de su actualización."
            ),
            responsible_organization=center,
            deadline=today + timedelta(days=20),
            evidence_requirements=(
                "Inventario conciliado y firmado.\nFotografías de los códigos colocados.\n"
                "Acuerdo de designación de la persona responsable."
            ),
            status=Recommendation.Status.PENDING,
        )
        decision = self._upsert_pending_decision(
            case,
            auditor,
            kind=CaseDecision.Kind.PUBLICATION,
            document=report,
            note=(
                "Se remite el informe y sus anexos para validar el alcance, los hallazgos, "
                "las recomendaciones y autorizar su publicación al centro educativo."
            ),
        )
        self._upsert_activity(
            case,
            auditor,
            "case_publication_requested",
            decision,
            {"demo": True, "document_version": report.version},
        )

    def _seed_under_review_case(self, center, auditor, institutional):
        today = date.today()
        case = self._upsert_case(
            "IA/NA-009-2025",
            title="Seguimiento a conciliaciones bancarias y libros auxiliares",
            audited_organization=center,
            report_date=today - timedelta(days=45),
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            response_deadline=today + timedelta(days=5),
            status=AuditCase.Status.UNDER_REVIEW,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        self._upsert_report_document(
            case,
            auditor,
            reference="INF-009-2025",
            title="Informe de seguimiento financiero",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            paragraphs=[
                "Se revisó la preparación mensual de conciliaciones bancarias y libros auxiliares.",
                "El centro remitió evidencia de la conciliación del último trimestre.",
            ],
        )
        finding = self._upsert_finding(
            case,
            1,
            title="Conciliaciones bancarias preparadas fuera de plazo",
            risk_level=Finding.RiskLevel.HIGH,
            condition="Tres conciliaciones mensuales fueron preparadas después del cierre del mes siguiente.",
            criteria="Las conciliaciones bancarias deben prepararse, revisarse y firmarse mensualmente.",
            cause="No existía un calendario de cierre ni una revisión independiente.",
            effect="Las diferencias bancarias pueden permanecer sin detectar durante varios meses.",
        )
        recommendation = self._upsert_recommendation(
            finding,
            1,
            text=(
                "Establezca un calendario de cierre y documente la preparación y revisión mensual "
                "de las conciliaciones bancarias."
            ),
            responsible_organization=center,
            deadline=today + timedelta(days=5),
            evidence_requirements="Calendario aprobado y conciliaciones del último trimestre firmadas.",
            status=Recommendation.Status.SUBMITTED,
        )
        response = self._upsert_pending_response(
            recommendation,
            institutional,
            declared_status=Response.DeclaredStatus.COMPLETED,
            action_description=(
                "El Consejo Directivo aprobó un calendario de cierre. Se prepararon y firmaron las "
                "conciliaciones de abril, mayo y junio y se designó una revisión independiente."
            ),
            action_date=today - timedelta(days=2),
            responsible_name="Responsable Institucional",
            responsible_job_title="Dirección del centro educativo",
            non_compliance_reason="",
            action_plan="",
            expected_completion_date=None,
            accuracy_declaration=True,
        )
        self._upsert_evidence(
            response,
            institutional,
            filename="conciliaciones-abril-junio.pdf",
            title="Conciliaciones bancarias de abril a junio",
            lines=[
                "Documento de demostración.",
                "Incluye firmas de elaboración, revisión y aprobación.",
                "Referencia del expediente: IA/NA-009-2025.",
            ],
            category=Evidence.Category.BANKING,
        )
        self._upsert_activity(
            case,
            institutional,
            "response_submitted",
            response,
            {"demo": True, "recommendation": recommendation.pk, "version": response.version},
        )

    def _seed_correction_case(self, center, auditor, institutional):
        today = date.today()
        case = self._upsert_case(
            "IA/NA-008-2025",
            title="Verificación del control y resguardo de bienes tecnológicos",
            audited_organization=center,
            report_date=today - timedelta(days=80),
            period_start=date(2023, 1, 1),
            period_end=date(2024, 6, 30),
            response_deadline=today + timedelta(days=8),
            status=AuditCase.Status.CORRECTION_REQUIRED,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        self._upsert_report_document(
            case,
            auditor,
            reference="INF-008-2025",
            title="Informe sobre bienes tecnológicos",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            paragraphs=[
                "Se evaluó el inventario, asignación y resguardo de computadoras y proyectores.",
                "La primera respuesta institucional fue revisada y requiere documentación adicional.",
            ],
        )
        finding = self._upsert_finding(
            case,
            1,
            title="Actas de asignación sin identificación completa",
            risk_level=Finding.RiskLevel.MEDIUM,
            condition="Cinco actas no indicaban número de inventario ni ubicación del equipo asignado.",
            criteria="Las actas de asignación deben identificar de forma inequívoca cada bien y custodio.",
            cause="Se utilizó un formato anterior que no incluye los campos de inventario y ubicación.",
            effect="No es posible atribuir con certeza la custodia de los equipos observados.",
        )
        recommendation = self._upsert_recommendation(
            finding,
            1,
            text="Actualice y firme las actas de asignación de los cinco equipos observados.",
            responsible_organization=center,
            deadline=today + timedelta(days=8),
            evidence_requirements="Cinco actas firmadas con número de inventario, ubicación y custodio.",
            status=Recommendation.Status.CORRECTION_REQUIRED,
        )
        response = self._upsert_response(
            recommendation,
            institutional,
            declared_status=Response.DeclaredStatus.IN_PROGRESS,
            action_description="Se actualizó el formato y se adjuntó un ejemplo de acta corregida.",
            action_date=today - timedelta(days=4),
            responsible_name="Responsable Institucional",
            responsible_job_title="Dirección del centro educativo",
            non_compliance_reason="",
            action_plan="Recabar las cuatro firmas restantes y remitir las cinco actas completas.",
            expected_completion_date=today + timedelta(days=5),
            accuracy_declaration=True,
        )
        self._upsert_evidence(
            response,
            institutional,
            filename="acta-asignacion-muestra.pdf",
            title="Muestra de acta de asignación actualizada",
            lines=[
                "Documento de demostración.",
                "La evidencia contiene solamente una de las cinco actas requeridas.",
            ],
            category=Evidence.Category.MINUTES,
        )
        review = self._upsert_review(
            response,
            auditor,
            outcome=Review.Outcome.CORRECTION_REQUIRED,
            comments=(
                "La evidencia acredita el nuevo formato, pero solo incluye una de las cinco actas. "
                "Adjunte las cinco actas firmadas con inventario, ubicación y custodio."
            ),
        )
        self._upsert_activity(
            case,
            auditor,
            "response_reviewed",
            review,
            {"demo": True, "outcome": review.outcome, "response": response.pk},
        )

    def _seed_pending_closure_case(self, center, auditor, institutional):
        today = date.today()
        case = self._upsert_case(
            "IA/NA-007-2024",
            title="Seguimiento final al manejo de fondos de actividades escolares",
            audited_organization=center,
            report_date=today - timedelta(days=150),
            period_start=date(2022, 1, 1),
            period_end=date(2023, 12, 31),
            response_deadline=today - timedelta(days=30),
            status=AuditCase.Status.PENDING_CLOSURE,
            assigned_auditor=auditor,
            created_by=auditor,
        )
        self._upsert_report_document(
            case,
            auditor,
            reference="INF-007-2024",
            title="Informe de seguimiento a fondos escolares",
            status=AuditDocument.Status.APPROVED,
            visibility=AuditDocument.Visibility.INSTITUTION,
            paragraphs=[
                "Las recomendaciones recibieron resultado técnico definitivo.",
                "El expediente se encuentra listo para decisión de cierre por la Dirección de Auditoría.",
            ],
        )
        finding = self._upsert_finding(
            case,
            1,
            title="Ausencia de liquidación consolidada de actividades",
            risk_level=Finding.RiskLevel.HIGH,
            condition="Las actividades escolares se liquidaban por separado sin un consolidado anual.",
            criteria="La administración debe rendir cuentas de todos los fondos recaudados y utilizados.",
            cause="No se había definido un formato institucional de liquidación.",
            effect="La comunidad educativa no disponía de una rendición de cuentas integral.",
        )
        recommendation = self._upsert_recommendation(
            finding,
            1,
            text="Prepare, apruebe y publique una liquidación anual consolidada de actividades escolares.",
            responsible_organization=center,
            deadline=today - timedelta(days=30),
            evidence_requirements="Liquidación firmada, acta de aprobación y constancia de publicación.",
            status=Recommendation.Status.COMPLIED,
        )
        response = self._upsert_response(
            recommendation,
            institutional,
            declared_status=Response.DeclaredStatus.COMPLETED,
            action_description=(
                "Se preparó la liquidación consolidada, fue aprobada por el Consejo Directivo "
                "y publicada para conocimiento de la comunidad educativa."
            ),
            action_date=today - timedelta(days=35),
            responsible_name="Responsable Institucional",
            responsible_job_title="Dirección del centro educativo",
            non_compliance_reason="",
            action_plan="",
            expected_completion_date=None,
            accuracy_declaration=True,
        )
        self._upsert_evidence(
            response,
            institutional,
            filename="liquidacion-anual-aprobada.pdf",
            title="Liquidación anual consolidada",
            lines=[
                "Documento de demostración.",
                "Liquidación aprobada y publicada por el centro educativo.",
            ],
            category=Evidence.Category.ACCOUNTING,
        )
        review = self._upsert_review(
            response,
            auditor,
            outcome=Review.Outcome.COMPLIED,
            comments="La liquidación, aprobación y publicación cumplen lo requerido.",
        )
        decision = self._upsert_pending_decision(
            case,
            auditor,
            kind=CaseDecision.Kind.CLOSURE,
            note=(
                "La recomendación cuenta con resultado definitivo de cumplimiento y no quedan "
                "acciones abiertas. Se solicita autorizar el cierre del expediente."
            ),
        )
        self._upsert_activity(
            case,
            auditor,
            "case_closure_requested",
            decision,
            {"demo": True, "justification": decision.request_note},
        )
