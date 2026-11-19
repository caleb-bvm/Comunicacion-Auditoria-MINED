import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


def avatar_upload_path(instance, filename):
    return f"perfiles/{uuid.uuid4().hex}.jpg"


phone_validator = RegexValidator(
    r"^\+?[0-9][0-9 -]{6,18}[0-9]$",
    "Escriba un teléfono válido, por ejemplo 2592-3000 o +503 7000-0000.",
)


class User(AbstractUser):
    class TextSize(models.TextChoices):
        NORMAL = "normal", "Normal"
        LARGE = "large", "Grande"

    class Role(models.TextChoices):
        TECHNICAL_ADMIN = "technical_admin", "Administrador técnico"
        AUDIT_MANAGER = "audit_manager", "Directora de Auditoría"
        AUDITOR = "auditor", "Auditor"
        INSTITUTION = "institution", "Responsable institucional"

    role = models.CharField("rol", max_length=24, choices=Role.choices, default=Role.INSTITUTION)
    organization = models.ForeignKey(
        "institutions.Organization",
        verbose_name="institución o dependencia",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    job_title = models.CharField("cargo", max_length=150, blank=True)
    phone = models.CharField(
        "teléfono", max_length=20, blank=True, db_default="", validators=[phone_validator]
    )
    avatar = models.FileField("foto de perfil", upload_to=avatar_upload_path, blank=True, db_default="")
    avatar_updated_at = models.DateTimeField("foto actualizada", null=True, blank=True, editable=False)
    password_changed_at = models.DateTimeField(
        "contraseña actualizada", null=True, blank=True, editable=False
    )
    text_size = models.CharField(
        "tamaño del texto", max_length=10, choices=TextSize.choices,
        default=TextSize.NORMAL, db_default=TextSize.NORMAL,
    )
    must_change_password = models.BooleanField("debe cambiar contraseña", default=True)
    activation_requested_at = models.DateTimeField(
        "activación solicitada", null=True, blank=True, editable=False
    )
    assigned_organizations = models.ManyToManyField(
        "institutions.Organization",
        verbose_name="organizaciones asignadas",
        blank=True,
        related_name="assigned_auditors",
    )

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def is_audit_staff(self):
        return self.is_superuser or self.role in {
            self.Role.AUDIT_MANAGER,
            self.Role.AUDITOR,
        }

    def set_password(self, raw_password):
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = [part for part in (self.first_name, self.last_name) if part.strip()]
        if parts:
            return "".join(part.strip()[0] for part in parts[:2]).upper()
        return (self.username[:1] or "?").upper()

    def clean(self):
        super().clean()
        if self.role == self.Role.INSTITUTION and not self.organization_id:
            raise ValidationError(
                {"organization": "Los responsables institucionales deben pertenecer a una institución."}
            )


class TechnicalSupportRequest(models.Model):
    class Category(models.TextChoices):
        PASSWORD_RESET = "password_reset", "Restablecimiento de contraseña"
        ACCOUNT_REACTIVATION = "account_reactivation", "Reactivación de cuenta"
        CLOSE_SESSIONS = "close_sessions", "Cierre de sesiones"
        ACCESS_DATA = "access_data", "Corrección de datos de acceso"
        TECHNICAL_ERROR = "technical_error", "Investigación de error"
        CATALOG = "catalog", "Corrección o importación de catálogo"
        OTHER = "other", "Otro soporte técnico"

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        IN_PROGRESS = "in_progress", "En atención"
        RESOLVED = "resolved", "Resuelta"
        CLOSED = "closed", "Cerrada"

    category = models.CharField("tipo", max_length=30, choices=Category.choices)
    subject = models.CharField("asunto", max_length=180)
    description = models.TextField("descripción")
    organization = models.ForeignKey(
        "institutions.Organization", verbose_name="institución relacionada",
        on_delete=models.PROTECT, null=True, blank=True, related_name="technical_requests",
    )
    requested_by = models.ForeignKey(
        User, verbose_name="solicitada por", on_delete=models.PROTECT,
        null=True, blank=True, related_name="requested_technical_support",
    )
    requester_name = models.CharField("nombre del solicitante", max_length=180, blank=True)
    requester_identifier = models.CharField("usuario o correo indicado", max_length=254, blank=True)
    requester_contact = models.EmailField("correo de contacto indicado", blank=True)
    is_public_request = models.BooleanField("solicitud pública", default=False)
    status = models.CharField("estado", max_length=20, choices=Status.choices, default=Status.OPEN)
    resolution = models.TextField("resolución", blank=True)
    handled_by = models.ForeignKey(
        User, verbose_name="atendida por", on_delete=models.PROTECT,
        null=True, blank=True, related_name="handled_technical_support",
    )
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)
    resolved_at = models.DateTimeField("resuelta", null=True, blank=True)
    reset_sent_at = models.DateTimeField("enlace de restablecimiento enviado", null=True, blank=True)

    class Meta:
        verbose_name = "solicitud técnica"
        verbose_name_plural = "solicitudes técnicas"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_category_display()}: {self.subject}"
