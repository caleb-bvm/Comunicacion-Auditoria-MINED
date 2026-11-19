from .security import client_ip, describe_device


def record_login(sender, request, user, **kwargs):
    """Registra cada ingreso para el panel de seguridad del perfil y la bitácora técnica."""
    if request is None:
        return
    from apps.audits.models import ActivityLog

    ActivityLog.objects.create(
        actor=user, action="login", target_type="User", target_id=str(user.pk),
        details={"device": describe_device(request.META.get("HTTP_USER_AGENT", ""))},
        ip_address=client_ip(request),
    )
