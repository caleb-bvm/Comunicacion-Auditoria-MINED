import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from apps.core.validators import validate_evidence_file


def cde_document_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    organization_id = getattr(instance, "organization_id", None)
    if not organization_id and hasattr(instance, "period"):
        organization_id = instance.period.organization_id
    return f"cde/institucion-{organization_id or 'pendiente'}/{uuid.uuid4().hex}{extension}"


class Organization(models.Model):
    class Kind(models.TextChoices):
        EDUCATIONAL_CENTER = "educational_center", "Centro educativo"
        DEPARTMENTAL_OFFICE = "departmental_office", "Dirección Departamental"
        MINISTRY_UNIT = "ministry_unit", "Unidad del Ministerio"
        OTHER = "other", "Otra institución"

    code = models.CharField("código institucional", max_length=30, unique=True)
    name = models.CharField("nombre", max_length=255)
    kind = models.CharField("tipo", max_length=30, choices=Kind.choices)
    department = models.CharField("departamento", max_length=100, blank=True)
    municipality = models.CharField("municipio", max_length=100, blank=True)
    district = models.CharField("distrito", max_length=100, blank=True)
    address = models.TextField("dirección", blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        verbose_name = "institución"
        verbose_name_plural = "instituciones"
        ordering = ("name",)

    def __str__(self):
        return f"{self.code} - {self.name}"


class SchoolBoardPeriod(models.Model):
    organization = models.ForeignKey(
        Organization,
        verbose_name="centro educativo",
        on_delete=models.PROTECT,
        related_name="school_board_periods",
    )
    start_date = models.DateField("fecha de inicio")
    end_date = models.DateField("fecha de finalización")
    school_year_start = models.PositiveSmallIntegerField(
        "año escolar inicial",
        validators=[MinValueValidator(1900)],
    )
    school_year_end = models.PositiveSmallIntegerField(
        "año escolar final",
        validators=[MinValueValidator(1900)],
    )
    supporting_document = models.FileField(
        "acta o documento de conformación",
        upload_to=cde_document_upload_path,
        validators=[validate_evidence_file],
    )
    supporting_document_name = models.CharField(
        "nombre original del documento",
        max_length=255,
        blank=True,
    )
    notes = models.TextField("observaciones", blank=True)
    is_current = models.BooleanField("vigente", default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.PROTECT,
        related_name="created_school_board_periods",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="actualizado por",
        on_delete=models.PROTECT,
        related_name="updated_school_board_periods",
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "período del Consejo Directivo Escolar"
        verbose_name_plural = "períodos del Consejo Directivo Escolar"
        ordering = ("-start_date", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("organization",),
                condition=models.Q(is_current=True),
                name="one_current_school_board_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="school_board_period_valid_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(school_year_end__gte=models.F("school_year_start")),
                name="school_board_period_valid_years",
            ),
        ]

    def clean(self):
        super().clean()
        if self.organization_id and self.organization.kind != Organization.Kind.EDUCATIONAL_CENTER:
            raise ValidationError(
                {"organization": "El CDE solamente puede registrarse para centros educativos."}
            )
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "La fecha de finalización no puede ser anterior al inicio."}
            )
        if (
            self.school_year_start
            and self.school_year_end
            and self.school_year_end < self.school_year_start
        ):
            raise ValidationError(
                {"school_year_end": "El año escolar final no puede ser anterior al inicial."}
            )

    @property
    def status_label(self):
        return "Vigente" if self.is_current else "Finalizado"

    def __str__(self):
        return (
            f"CDE {self.organization.code} "
            f"({self.school_year_start}-{self.school_year_end})"
        )


class SchoolBoardMember(models.Model):
    class Sector(models.TextChoices):
        PARENTS = "parents", "Padres de familia"
        TEACHERS = "teachers", "Docentes"
        STUDENTS = "students", "Estudiantes"
        DIRECTORATE = "directorate", "Dirección del centro"
        OTHER = "other", "Otro sector"

    period = models.ForeignKey(
        SchoolBoardPeriod,
        verbose_name="período del CDE",
        on_delete=models.PROTECT,
        related_name="members",
    )
    full_name = models.CharField("nombre completo", max_length=255)
    identity_document = models.CharField(
        "DUI (Documento Único de Identidad)",
        max_length=10,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^\d{8}-\d$",
                message="Ingrese el DUI con el formato 00000000-0.",
                code="invalid_dui_format",
            )
        ],
    )
    position = models.CharField("cargo dentro del CDE", max_length=150)
    sector = models.CharField("sector que representa", max_length=20, choices=Sector.choices)
    is_legal_representative = models.BooleanField("ejerce representación legal", default=False)
    joined_on = models.DateField("fecha de incorporación")
    left_on = models.DateField("fecha de salida", null=True, blank=True)
    exit_reason = models.TextField("motivo de salida o sustitución", blank=True)
    change_document = models.FileField(
        "documento de respaldo de la salida o sustitución",
        upload_to=cde_document_upload_path,
        validators=[validate_evidence_file],
        blank=True,
    )
    change_document_name = models.CharField(
        "nombre original del documento de cambio",
        max_length=255,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="registrado por",
        on_delete=models.PROTECT,
        related_name="created_school_board_members",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="actualizado por",
        on_delete=models.PROTECT,
        related_name="updated_school_board_members",
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        verbose_name = "integrante del Consejo Directivo Escolar"
        verbose_name_plural = "integrantes del Consejo Directivo Escolar"
        ordering = ("left_on", "position", "full_name")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(left_on__isnull=True)
                | models.Q(left_on__gte=models.F("joined_on")),
                name="school_board_member_valid_dates",
            )
        ]

    def clean(self):
        super().clean()
        if self.period_id and self.joined_on:
            if self.joined_on < self.period.start_date or self.joined_on > self.period.end_date:
                raise ValidationError(
                    {
                        "joined_on": (
                            "La incorporación debe estar comprendida dentro del período del CDE."
                        )
                    }
                )
        if self.left_on and self.joined_on and self.left_on < self.joined_on:
            raise ValidationError(
                {"left_on": "La fecha de salida no puede ser anterior a la incorporación."}
            )
        if self.period_id and self.left_on and self.left_on > self.period.end_date:
            raise ValidationError(
                {"left_on": "La fecha de salida debe estar comprendida dentro del período del CDE."}
            )
        if self.left_on and not self.exit_reason.strip():
            raise ValidationError(
                {"exit_reason": "Indique el motivo de la salida o sustitución."}
            )

    @property
    def is_active(self):
        return self.left_on is None

    def __str__(self):
        return f"{self.full_name} - {self.position}"
