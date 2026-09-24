from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
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
            self.Role.TECHNICAL_ADMIN,
            self.Role.AUDIT_MANAGER,
            self.Role.AUDITOR,
        }

    def clean(self):
        super().clean()
        if self.role == self.Role.INSTITUTION and not self.organization_id:
            raise ValidationError(
                {"organization": "Los responsables institucionales deben pertenecer a una institución."}
            )
