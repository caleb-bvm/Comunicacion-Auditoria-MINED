import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.core.validators import validate_evidence_file


def private_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    case_id = getattr(instance, "case_id", None)
    if not case_id and hasattr(instance, "response"):
        case_id = instance.response.recommendation.finding.case_id
    return f"expedientes/{case_id or 'pendiente'}/{uuid.uuid4().hex}{extension}"


def audit_document_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    location = f"expediente-{instance.case_id}" if instance.case_id else f"institucion-{instance.organization_id}"
    return f"documentos/{location}/{uuid.uuid4().hex}{extension}"


class AuditCase(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PENDING_PUBLICATION = "pending_publication", "Pendiente de aprobación"
        PUBLISHED = "published", "Enviado"
        IN_RESPONSE = "in_response", "En respuesta"
        UNDER_REVIEW = "under_review", "En revisión"
        CORRECTION_REQUIRED = "correction_required", "Requiere corrección"
        PENDING_CLOSURE = "pending_closure", "Cierre solicitado"
        CLOSED = "closed", "Cerrado"

    reference = models.CharField("referencia", max_length=60, unique=True)
    title = models.CharField("título", max_length=300)
    audited_organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="institución auditada",
        on_delete=models.PROTECT,
        related_name="audit_cases",
    )
    report_file = models.FileField(
        "informe PDF",
        upload_to=private_upload_path,
        validators=[validate_evidence_file],
        blank=True,
    )
    report_date = models.DateField("fecha del informe", null=True, blank=True)
    period_start = models.DateField("inicio del período", null=True, blank=True)
    period_end = models.DateField("fin del período", null=True, blank=True)
    response_deadline = models.DateField("fecha límite general", null=True, blank=True)
    status = models.CharField("estado", max_length=30, choices=Status.choices, default=Status.DRAFT)
    assigned_auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auditor responsable",
        on_delete=models.PROTECT,
        related_name="assigned_cases",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="creado por",
        on_delete=models.PROTECT,
        related_name="created_cases",
    )
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "expediente de auditoría"
        verbose_name_plural = "expedientes de auditoría"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.reference} - {self.audited_organization.name}"


class AuditDocument(models.Model):
    class DocumentType(models.TextChoices):
        HISTORICAL_REPORT = "historical_report", "Informe anterior"
        REPORT = "report", "Informe del expediente"
        NOTIFICATION = "notification", "Notificación"
        HISTORICAL_RESPONSE = "historical_response", "Respuesta anterior"
        HISTORICAL_EVIDENCE = "historical_evidence", "Evidencia anterior"
        HISTORICAL_EXTENSION = "historical_extension", "Prórroga anterior"
        HISTORICAL_CLOSURE = "historical_closure", "Cierre anterior"
        OTHER = "other", "Otro documento"

    class Status(models.TextChoices):
        HISTORICAL = "historical", "Anterior"
        DRAFT = "draft", "Borrador"
        PENDING_APPROVAL = "pending_approval", "Pendiente de aprobación"
        APPROVED = "approved", "Aprobado"
        RETURNED = "returned", "Devuelto"

    class Visibility(models.TextChoices):
        AUDIT_ONLY = "audit_only", "Solo Auditoría"
        INSTITUTION = "institution", "Visible para la institución"

    case = models.ForeignKey(
        AuditCase,
        verbose_name="expediente",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documents",
    )
    organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="institución",
        on_delete=models.PROTECT,
        related_name="audit_documents",
    )
    document_type = models.CharField(
        "tipo de documento",
        max_length=30,
        choices=DocumentType.choices,
    )
    reference = models.CharField("referencia", max_length=80, blank=True)
    parent_report = models.ForeignKey(
        "self", verbose_name="informe anterior relacionado", on_delete=models.PROTECT,
        null=True, blank=True, related_name="attachments",
        limit_choices_to={"document_type": "historical_report", "parent_report__isnull": True},
    )
    title = models.CharField("título", max_length=300)
    document_date = models.DateField("fecha del documento", null=True, blank=True)
    version = models.PositiveIntegerField("versión", default=1, validators=[MinValueValidator(1)])
    status = models.CharField("estado", max_length=24, choices=Status.choices)
    visibility = models.CharField(
        "visibilidad",
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.AUDIT_ONLY,
    )
    file = models.FileField(
        "archivo",
        upload_to=audit_document_upload_path,
        validators=[validate_evidence_file],
    )
    original_filename = models.CharField("nombre original", max_length=255)
    size = models.PositiveBigIntegerField("tamaño", default=0)
    sha256 = models.CharField("huella SHA-256", max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="cargado por",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="uploaded_audit_documents",
    )
    uploaded_at = models.DateTimeField("cargado", auto_now_add=True)

    class Meta:
        verbose_name = "documento de auditoría"
        verbose_name_plural = "documentos de auditoría"
        ordering = ("-document_date", "-uploaded_at")
        constraints = [
            models.UniqueConstraint(
                fields=("case", "document_type", "version"),
                condition=models.Q(case__isnull=False),
                name="unique_document_version_per_case_and_type",
            ),
            models.UniqueConstraint(
                fields=("parent_report", "sha256"),
                condition=models.Q(parent_report__isnull=False),
                name="unique_file_per_historical_report",
            ),
        ]

    def clean(self):
        super().clean()
        archived_types = {self.DocumentType.HISTORICAL_RESPONSE, self.DocumentType.HISTORICAL_EVIDENCE,
                          self.DocumentType.HISTORICAL_EXTENSION, self.DocumentType.HISTORICAL_CLOSURE}
        if self.document_type in archived_types and not self.parent_report_id:
            raise ValidationError({"parent_report": "Seleccione el informe anterior al que pertenece el documento."})
        if self.parent_report_id:
            parent = self.parent_report
            if (parent.document_type != self.DocumentType.HISTORICAL_REPORT
                    or parent.parent_report_id or parent.case_id or parent.pk == self.pk
                    or parent.organization_id != self.organization_id
                    or parent.status != self.Status.HISTORICAL):
                raise ValidationError({"parent_report": "El documento debe pertenecer a un informe anterior del mismo centro."})
            if (self.case_id or self.status != self.Status.HISTORICAL
                    or self.document_type in {self.DocumentType.REPORT, self.DocumentType.HISTORICAL_REPORT}):
                raise ValidationError("Los anexos históricos deben conservar su clasificación y estado anterior.")

    def __str__(self):
        return f"{self.reference or self.title} / v{self.version}"


class HistoricalRecommendation(models.Model):
    class Status(models.TextChoices):
        PARTIAL = "partial", "Parcialmente cumplida"
        NOT_COMPLIED = "not_complied", "No cumplida"

    source_document = models.ForeignKey(
        AuditDocument,
        verbose_name="informe de origen",
        on_delete=models.PROTECT,
        related_name="historical_recommendations",
        limit_choices_to={"document_type": AuditDocument.DocumentType.HISTORICAL_REPORT},
    )
    number = models.CharField("número o literal", max_length=60)
    text = models.TextField("recomendación")
    responsible_organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="institución responsable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="historical_recommendations",
    )
    responsible_description = models.CharField(
        "responsable indicado en el informe",
        max_length=300,
        blank=True,
    )
    status = models.CharField("estado anterior", max_length=20, choices=Status.choices)
    comments = models.TextField("comentario anterior", blank=True)
    original_deadline = models.DateField("fecha límite original", null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrada por",
        on_delete=models.PROTECT,
        related_name="recorded_historical_recommendations",
    )
    recorded_at = models.DateTimeField("registrada", auto_now_add=True)

    class Meta:
        verbose_name = "recomendación histórica"
        verbose_name_plural = "recomendaciones históricas"
        ordering = ("source_document__document_date", "number")
        constraints = [
            models.UniqueConstraint(
                fields=("source_document", "number"),
                name="unique_historical_recommendation_number_per_document",
            )
        ]

    def __str__(self):
        return f"{self.source_document.reference or self.source_document.title} / {self.number}"


class Finding(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "low", "Bajo"
        MEDIUM = "medium", "Medio"
        HIGH = "high", "Alto"
        CRITICAL = "critical", "Crítico"

    case = models.ForeignKey(AuditCase, verbose_name="expediente", on_delete=models.CASCADE, related_name="findings")
    number = models.PositiveIntegerField("número", validators=[MinValueValidator(1)])
    title = models.CharField("título", max_length=350)
    risk_level = models.CharField("riesgo", max_length=10, choices=RiskLevel.choices)
    condition = models.TextField("condición", blank=True)
    criteria = models.TextField("criterio", blank=True)
    cause = models.TextField("causa", blank=True)
    effect = models.TextField("efecto", blank=True)

    class Meta:
        verbose_name = "hallazgo"
        verbose_name_plural = "hallazgos"
        ordering = ("number",)
        constraints = [
            models.UniqueConstraint(fields=("case", "number"), name="unique_finding_number_per_case")
        ]

    def __str__(self):
        return f"Hallazgo {self.number}: {self.title}"


class Recommendation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        SUBMITTED = "submitted", "Respuesta enviada"
        UNDER_REVIEW = "under_review", "En revisión"
        CORRECTION_REQUIRED = "correction_required", "Requiere corrección"
        COMPLIED = "complied", "Cumplida"
        PARTIAL = "partial", "Parcialmente cumplida"
        NOT_COMPLIED = "not_complied", "No cumplida"

    finding = models.ForeignKey(Finding, verbose_name="hallazgo", on_delete=models.CASCADE, related_name="recommendations")
    number = models.PositiveIntegerField("número", validators=[MinValueValidator(1)])
    text = models.TextField("recomendación")
    responsible_organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="institución responsable",
        on_delete=models.PROTECT,
        related_name="recommendations",
    )
    deadline = models.DateField("fecha límite", null=True, blank=True)
    evidence_requirements = models.TextField("evidencias requeridas", blank=True)
    status = models.CharField("estado", max_length=30, choices=Status.choices, default=Status.PENDING)
    source_recommendation = models.ForeignKey(
        HistoricalRecommendation,
        verbose_name="recomendación histórica de origen",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="follow_up_recommendations",
    )
    carried_from = models.ForeignKey(
        "self",
        verbose_name="recomendación anterior",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="carried_forward_recommendations",
    )
    no_response_recorded_at = models.DateTimeField(
        "incumplimiento automático registrado",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "recomendación"
        verbose_name_plural = "recomendaciones"
        ordering = ("finding__number", "number")
        constraints = [
            models.UniqueConstraint(
                fields=("finding", "number"), name="unique_recommendation_number_per_finding"
            )
        ]

    def __str__(self):
        return f"{self.finding.case.reference} / H{self.finding.number} / R{self.number}"

    @property
    def effective_deadline(self):
        latest_extension = self.deadline_extensions.order_by("-granted_at", "-pk").first()
        return latest_extension.new_deadline if latest_extension else self.deadline


class BusinessDayHoliday(models.Model):
    date = models.DateField("fecha", unique=True)
    name = models.CharField("nombre", max_length=160)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "asueto"
        verbose_name_plural = "asuetos"
        ordering = ("date",)

    def __str__(self):
        return f"{self.date:%d/%m/%Y} - {self.name}"


class DeadlineExtension(models.Model):
    recommendation = models.ForeignKey(
        Recommendation,
        verbose_name="recomendación",
        on_delete=models.PROTECT,
        related_name="deadline_extensions",
    )
    previous_deadline = models.DateField("fecha límite anterior")
    business_days = models.PositiveIntegerField(
        "días hábiles concedidos",
        validators=[MinValueValidator(1)],
    )
    new_deadline = models.DateField("nueva fecha límite")
    reason = models.TextField("motivo")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrada por",
        on_delete=models.PROTECT,
        related_name="granted_deadline_extensions",
    )
    granted_at = models.DateTimeField("registrada", auto_now_add=True)

    class Meta:
        verbose_name = "prórroga"
        verbose_name_plural = "prórrogas"
        ordering = ("granted_at",)

    def __str__(self):
        return f"{self.recommendation} hasta {self.new_deadline:%d/%m/%Y}"


class Response(models.Model):
    class DeclaredStatus(models.TextChoices):
        NOT_STARTED = "not_started", "No iniciada"
        IN_PROGRESS = "in_progress", "En proceso"
        COMPLETED = "completed", "Completada"
        UNABLE = "unable", "No fue posible cumplir"

    recommendation = models.ForeignKey(
        Recommendation, verbose_name="recomendación", on_delete=models.PROTECT, related_name="responses"
    )
    version = models.PositiveIntegerField("versión", validators=[MinValueValidator(1)])
    declared_status = models.CharField("estado declarado", max_length=20, choices=DeclaredStatus.choices)
    action_description = models.TextField("acciones realizadas")
    action_date = models.DateField("fecha de ejecución", null=True, blank=True)
    responsible_name = models.CharField("nombre del responsable", max_length=200)
    responsible_job_title = models.CharField("cargo del responsable", max_length=150)
    non_compliance_reason = models.TextField("motivo de incumplimiento", blank=True)
    action_plan = models.TextField("plan de acción pendiente", blank=True)
    expected_completion_date = models.DateField("fecha estimada de cumplimiento", null=True, blank=True)
    accuracy_declaration = models.BooleanField("declaración de veracidad", default=False)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="enviada por",
        on_delete=models.PROTECT,
        related_name="submitted_responses",
    )
    school_board_period = models.ForeignKey(
        "institutions.SchoolBoardPeriod",
        verbose_name="CDE vigente al presentar la respuesta",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="responses",
    )
    submitted_at = models.DateTimeField("enviada", auto_now_add=True)

    class Meta:
        verbose_name = "respuesta"
        verbose_name_plural = "respuestas"
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(
                fields=("recommendation", "version"), name="unique_response_version_per_recommendation"
            )
        ]

    def __str__(self):
        return f"{self.recommendation} / versión {self.version}"


class Evidence(models.Model):
    class Category(models.TextChoices):
        MINUTES = "minutes", "Acta"
        ACCOUNTING = "accounting", "Registro contable"
        BANKING = "banking", "Documento bancario"
        INVOICE = "invoice", "Factura o recibo"
        CONTRACT = "contract", "Contrato"
        IMAGE = "image", "Imagen"
        OTHER = "other", "Otra evidencia"

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pendiente de análisis"
        CLEAN = "clean", "Aprobado"
        REJECTED = "rejected", "Rechazado"

    response = models.ForeignKey(Response, verbose_name="respuesta", on_delete=models.CASCADE, related_name="evidence")
    file = models.FileField("archivo", upload_to=private_upload_path, validators=[validate_evidence_file])
    original_filename = models.CharField("nombre original", max_length=255)
    category = models.CharField("categoría", max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.CharField("descripción", max_length=300)
    size = models.PositiveBigIntegerField("tamaño", default=0)
    sha256 = models.CharField("huella SHA-256", max_length=64)
    scan_status = models.CharField(
        "estado de análisis", max_length=10, choices=ScanStatus.choices, default=ScanStatus.PENDING
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="subida por",
        on_delete=models.PROTECT,
        related_name="uploaded_evidence",
    )
    uploaded_at = models.DateTimeField("subida", auto_now_add=True)

    class Meta:
        verbose_name = "evidencia"
        verbose_name_plural = "evidencias"
        ordering = ("uploaded_at",)

    def __str__(self):
        return self.original_filename


class Review(models.Model):
    class Outcome(models.TextChoices):
        CORRECTION_REQUIRED = "correction_required", "Requiere corrección"
        COMPLIED = "complied", "Cumplida"
        PARTIAL = "partial", "Parcialmente cumplida"
        NOT_COMPLIED = "not_complied", "No cumplida"

    response = models.OneToOneField(Response, verbose_name="respuesta", on_delete=models.PROTECT, related_name="review")
    outcome = models.CharField("resultado", max_length=30, choices=Outcome.choices)
    comments = models.TextField("comentarios de Auditoría")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="revisada por",
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    reviewed_at = models.DateTimeField("revisada", auto_now_add=True)

    class Meta:
        verbose_name = "revisión"
        verbose_name_plural = "revisiones"
        ordering = ("-reviewed_at",)

    def __str__(self):
        return f"{self.response} - {self.get_outcome_display()}"


class AuditorPortfolioChange(models.Model):
    class Action(models.TextChoices):
        ASSIGN = "assign", "Asignación"
        UNASSIGN = "unassign", "Desasignación"

    class Outcome(models.TextChoices):
        APPLIED = "applied", "Aplicada"
        SKIPPED = "skipped", "Omitida"
        BLOCKED = "blocked", "Bloqueada"

    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auditor",
        on_delete=models.PROTECT,
        related_name="portfolio_changes",
    )
    organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="organización",
        on_delete=models.PROTECT,
        related_name="auditor_portfolio_changes",
    )
    action = models.CharField("acción", max_length=12, choices=Action.choices)
    outcome = models.CharField("resultado", max_length=12, choices=Outcome.choices)
    reason = models.CharField("motivo", max_length=500, blank=True)
    outcome_detail = models.CharField("detalle del resultado", max_length=300, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="realizado por",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="portfolio_changes_made",
    )
    batch_id = models.UUIDField("operación", db_index=True)
    is_bulk = models.BooleanField("operación masiva", default=False)
    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "cambio de cartera de auditor"
        verbose_name_plural = "historial de cartera de auditores"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("auditor", "created_at"), name="auditor_portfolio_history"),
            models.Index(fields=("organization", "created_at"), name="org_portfolio_history"),
        ]


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    case = models.ForeignKey(
        AuditCase,
        verbose_name="expediente",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    action = models.CharField("acción", max_length=80)
    target_type = models.CharField("tipo de objeto", max_length=80, blank=True)
    target_id = models.CharField("identificador", max_length=80, blank=True)
    details = models.JSONField("detalles", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("dirección IP", null=True, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "evento de bitácora"
        verbose_name_plural = "bitácora"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} - {self.action}"


class CaseDecision(models.Model):
    class Kind(models.TextChoices):
        PUBLICATION = "publication", "Publicación"
        CLOSURE = "closure", "Cierre"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        APPROVED = "approved", "Aprobada"
        RETURNED = "returned", "Devuelta"

    case = models.ForeignKey(
        AuditCase,
        verbose_name="expediente",
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    document = models.ForeignKey(
        AuditDocument,
        verbose_name="documento sometido",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decisions",
    )
    kind = models.CharField("tipo de decisión", max_length=20, choices=Kind.choices)
    status = models.CharField(
        "estado", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    request_note = models.TextField("nota de solicitud", blank=True)
    previous_case_status = models.CharField("estado anterior", max_length=30, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="solicitada por",
        on_delete=models.PROTECT,
        related_name="requested_case_decisions",
    )
    requested_at = models.DateTimeField("solicitada", auto_now_add=True)
    decision_note = models.TextField("justificación de la decisión", blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="decidida por",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_case_decisions",
    )
    decided_at = models.DateTimeField("decidida", null=True, blank=True)

    class Meta:
        verbose_name = "decisión directiva"
        verbose_name_plural = "decisiones directivas"
        ordering = ("-requested_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("case",),
                condition=models.Q(status="pending"),
                name="one_pending_decision_per_case",
            )
        ]

    def __str__(self):
        return f"{self.case.reference} - {self.get_kind_display()} - {self.get_status_display()}"
