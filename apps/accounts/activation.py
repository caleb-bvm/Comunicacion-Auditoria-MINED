from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.institutions.models import Organization
from .models import User


class ActivationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "accounts.center_activation"

    def _make_hash_value(self, user, timestamp):
        return (
            super()._make_hash_value(user, timestamp)
            + f"{user.is_active}:{user.role}:{user.organization_id}:"
            + f"{user.activation_requested_at}:{user.organization.email}"
        )

    def check_token(self, user, token):
        if (
            not user or user.is_active or user.has_usable_password()
            or not user.activation_requested_at
            or user.role != User.Role.INSTITUTION
            or not user.organization_id
            or user.organization.kind != Organization.Kind.EDUCATIONAL_CENTER
            or not user.organization.is_active
            or user.email != user.organization.email
        ):
            return False
        return super().check_token(user, token)


activation_token_generator = ActivationTokenGenerator()


@transaction.atomic
def invite_center(*, center_id, actor, request):
    """Keep access disabled until a single-use invitation is redeemed."""
    from apps.audits.models import ActivityLog

    center = Organization.objects.select_for_update().get(
        pk=center_id, kind=Organization.Kind.EDUCATIONAL_CENTER
    )
    if not center.email:
        raise ValidationError("Registre el correo institucional antes de activar el acceso.")
    validate_email(center.email)
    if Organization.objects.exclude(pk=center.pk).filter(email__iexact=center.email).exists():
        raise ValidationError("El correo también está asignado a otra institución. Revise el catálogo.")
    accounts = User.objects.select_for_update().filter(
        organization=center, role=User.Role.INSTITUTION
    )
    if accounts.filter(is_active=True).exists():
        raise ValidationError("Este centro ya tiene acceso activo.")
    if accounts.count() > 1:
        raise ValidationError("Este centro tiene varias cuentas. Administración debe revisar cuál habilitar.")
    account = accounts.first()
    created = account is None
    if User.objects.filter(username=center.code).exclude(pk=account.pk if account else None).exists():
        raise ValidationError("El código del centro ya está utilizado como usuario. Solicite su revisión.")
    if User.objects.filter(email__iexact=center.email).exclude(
        organization=center, role=User.Role.INSTITUTION
    ).exists():
        raise ValidationError("El correo está vinculado a una cuenta ajena al centro. Solicite su revisión.")
    if account is None:
        account = User(organization=center, role=User.Role.INSTITUTION,
                       first_name="Responsable", last_name="Institucional",
                       job_title="Dirección del centro educativo")
    # A reissued invitation revokes the previous link and any old credential.
    account.username = center.code
    account.email = center.email
    account.is_active = False
    account.is_staff = False
    account.is_superuser = False
    account.must_change_password = True
    account.activation_requested_at = timezone.now()
    account.set_unusable_password()
    account.save()

    origin = settings.PUBLIC_BASE_URL.rstrip("/")
    if not origin and settings.DEBUG:
        origin = request.build_absolute_uri("/").rstrip("/")
    parsed = urlsplit(origin)
    if (not parsed.netloc or parsed.path or parsed.query or parsed.fragment
            or parsed.username or parsed.password
            or parsed.scheme not in ({"http", "https"} if settings.DEBUG else {"https"})):
        raise ValidationError("Configure la dirección pública del sistema para enviar activaciones.")
    path = reverse("activate_account", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(account.pk)),
        "token": activation_token_generator.make_token(account),
    })
    hours = settings.PASSWORD_RESET_TIMEOUT // 3600
    body = (
        f"Se ha solicitado el acceso de {center.name} a SIGA-MINEDUCYT.\n\n"
        f"Su usuario es el código del centro: {account.username}\n"
        f"Establezca su contraseña mediante este enlace (válido por {hours} horas):\n"
        f"{origin}{path}\n\n"
        "El enlace solo puede utilizarse una vez. Si no reconoce esta solicitud, "
        "comuníquese con la Dirección de Auditoría."
    )
    if send_mail("Activación de acceso | SIGA-MINEDUCYT", body,
                 settings.DEFAULT_FROM_EMAIL, [center.email], fail_silently=False) != 1:
        raise ValidationError("No se pudo enviar la invitación. Inténtelo nuevamente.")
    # Preserve the existing pilot's ability to reactivate a catalog entry explicitly.
    if not center.is_active:
        center.is_active = True
        center.save(update_fields=["is_active", "updated_at"])
    ActivityLog.objects.create(
        actor=actor, action="educational_center_invited", target_type="Organization",
        target_id=str(center.pk), details={"organization_code": center.code,
        "institutional_user_id": account.pk, "username": account.username,
        "account_created": created, "email": account.email},
    )
    return account
