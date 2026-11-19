"""Pantalla «Mi perfil»: datos personales, foto, seguridad, resumen del rol y preferencias."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .avatars import AVATAR_ACCEPT, AVATAR_MAX_MB, remove_avatar, replace_avatar, user_can_view_avatar
from .models import TechnicalSupportRequest, User
from .security import client_ip, close_user_sessions, count_user_sessions

RECENT_LOGINS = 5


class PersonalDataForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "job_title", "phone")
        labels = {"first_name": "Nombres", "last_name": "Apellidos", "job_title": "Cargo", "phone": "Teléfono"}
        help_texts = {
            "job_title": "Por ejemplo: Director, Subdirectora, Auditor II.",
            "phone": "Un número donde Auditoría Interna pueda localizarle.",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "job_title": forms.TextInput(attrs={"autocomplete": "organization-title"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        for name in ("first_name", "last_name", "job_title", "phone"):
            self.fields[name].strip = True


class AvatarForm(forms.Form):
    photo = forms.FileField(
        label="Nueva foto",
        help_text=f"JPG o PNG de hasta {AVATAR_MAX_MB} MB. Se recorta en cuadrado al centro.",
        widget=forms.ClearableFileInput(attrs={"accept": AVATAR_ACCEPT, "data-avatar-input": ""}),
    )


class PreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("text_size",)
        labels = {"text_size": "Tamaño del texto"}
        widgets = {"text_size": forms.RadioSelect}


def _log(request, action, details=None):
    from apps.audits.models import ActivityLog

    ActivityLog.objects.create(
        actor=request.user, action=action, target_type="User", target_id=str(request.user.pk),
        details=details or {}, ip_address=client_ip(request),
    )


def _figure(value, label, url=""):
    return {"value": value, "label": label, "url": url}


def role_summary(user):
    """Cifras y datos propios del rol. Cada consulta respeta el mismo alcance que el resto del sistema."""
    from apps.audits.models import AuditCase, CaseDecision, Recommendation
    from apps.audits.services import with_effective_deadline
    from apps.institutions.models import SchoolBoardPeriod

    today = timezone.localdate()
    open_case_states = [
        AuditCase.Status.PUBLISHED, AuditCase.Status.IN_RESPONSE, AuditCase.Status.UNDER_REVIEW,
        AuditCase.Status.CORRECTION_REQUIRED, AuditCase.Status.PENDING_CLOSURE,
    ]
    waiting_states = [Recommendation.Status.PENDING, Recommendation.Status.CORRECTION_REQUIRED]
    case_list = reverse("case_list")
    summary = {"title": "", "figures": [], "facts": [], "links": []}

    if user.role == User.Role.AUDITOR:
        cases = AuditCase.objects.filter(assigned_auditor=user)
        recommendations = Recommendation.objects.filter(finding__case__assigned_auditor=user)
        overdue = with_effective_deadline(
            recommendations.filter(status__in=waiting_states, finding__case__status__in=open_case_states)
        ).filter(current_deadline__lt=today)
        summary["title"] = "Su trabajo"
        summary["figures"] = [
            _figure(cases.filter(status__in=open_case_states).count(), "Expedientes en curso", case_list),
            _figure(
                recommendations.filter(status__in=[
                    Recommendation.Status.SUBMITTED, Recommendation.Status.UNDER_REVIEW,
                ]).count(),
                "Respuestas por revisar", case_list,
            ),
            _figure(overdue.count(), "Recomendaciones vencidas"),
            _figure(user.assigned_organizations.count(), "Organizaciones asignadas"),
        ]
        summary["facts"] = [
            ("Borradores", cases.filter(status=AuditCase.Status.DRAFT).count()),
            ("Pendientes de aprobación", cases.filter(status=AuditCase.Status.PENDING_PUBLICATION).count()),
            ("Expedientes cerrados", cases.filter(status=AuditCase.Status.CLOSED).count()),
        ]
        summary["links"] = [("Ver expedientes", case_list), ("Nuevo expediente", reverse("case_create"))]
    elif user.role == User.Role.INSTITUTION and user.organization_id:
        organization = user.organization
        recommendations = Recommendation.objects.filter(
            responsible_organization=organization, finding__case__status__in=open_case_states,
        )
        waiting = with_effective_deadline(recommendations.filter(status__in=waiting_states))
        board = SchoolBoardPeriod.objects.filter(organization=organization, is_current=True).first()
        summary["title"] = "Su centro"
        summary["figures"] = [
            _figure(waiting.count(), "Recomendaciones por atender", case_list),
            _figure(waiting.filter(current_deadline__lt=today).count(), "Vencidas", case_list),
            _figure(
                recommendations.filter(status__in=[
                    Recommendation.Status.SUBMITTED, Recommendation.Status.UNDER_REVIEW,
                ]).count(),
                "En revisión de Auditoría",
            ),
        ]
        summary["facts"] = [
            ("Nombre", organization.name),
            ("Código", organization.code),
            ("Departamento", organization.department or "Sin registrar"),
            ("Distrito", organization.district or "Sin registrar"),
            (
                "Consejo Directivo vigente",
                f"{board.start_date:%d/%m/%Y} al {board.end_date:%d/%m/%Y}" if board else "Sin período registrado",
            ),
        ]
        summary["links"] = [
            ("Ver expedientes", case_list),
            ("Consejo Directivo Escolar", reverse("cde_home")),
            ("Historial", reverse("institution_history")),
        ]
    elif user.role == User.Role.AUDIT_MANAGER or (user.is_superuser and user.role != User.Role.TECHNICAL_ADMIN):
        summary["title"] = "Dirección"
        summary["figures"] = [
            _figure(
                CaseDecision.objects.filter(status=CaseDecision.Status.PENDING).count(),
                "Decisiones pendientes", reverse("director_decisions"),
            ),
            _figure(
                AuditCase.objects.filter(status__in=open_case_states).count(),
                "Expedientes en curso", case_list,
            ),
            _figure(
                User.objects.filter(role=User.Role.AUDITOR, is_active=True).count(),
                "Auditores activos", reverse("director_auditors"),
            ),
        ]
    elif user.role == User.Role.TECHNICAL_ADMIN:
        summary["title"] = "Administración técnica"
        summary["figures"] = [
            _figure(
                TechnicalSupportRequest.objects.filter(status__in=[
                    TechnicalSupportRequest.Status.OPEN, TechnicalSupportRequest.Status.IN_PROGRESS,
                ]).count(),
                "Solicitudes abiertas", reverse("technical_support_requests"),
            ),
            _figure(User.objects.filter(is_active=True).count(), "Usuarios activos", reverse("technical_users")),
        ]
    return summary


def security_summary(request):
    from apps.audits.models import ActivityLog

    user = request.user
    logins = list(
        ActivityLog.objects.filter(actor=user, action="login").order_by("-created_at")[:RECENT_LOGINS + 1]
    )
    return {
        # El ingreso más reciente es casi siempre esta misma sesión; el anterior es el dato útil.
        "previous_login": logins[1] if len(logins) > 1 else None,
        "recent_logins": logins[:RECENT_LOGINS],
        "password_changed_at": user.password_changed_at,
        "session_count": count_user_sessions(user),
        "is_internal": user.role != User.Role.INSTITUTION,
    }


@login_required
@require_http_methods(["GET", "POST"])
def account_profile(request):
    user = request.user
    personal_form = PersonalDataForm(instance=user, prefix="personal")
    avatar_form = AvatarForm(prefix="avatar")
    preferences_form = PreferencesForm(instance=user, prefix="preferences")
    if request.method == "POST":
        section = request.POST.get("section")
        if section == "personal":
            personal_form = PersonalDataForm(request.POST, instance=user, prefix="personal")
            if personal_form.is_valid():
                changed = personal_form.changed_data
                if changed:
                    personal_form.save()
                    _log(request, "profile_updated", {"fields": changed})
                    messages.success(request, "Sus datos se guardaron.")
                else:
                    messages.info(request, "No había cambios que guardar.")
                return redirect(f"{reverse('account_profile')}#datos")
        elif section == "avatar":
            avatar_form = AvatarForm(request.POST, request.FILES, prefix="avatar")
            if avatar_form.is_valid():
                try:
                    replace_avatar(user, avatar_form.cleaned_data["photo"])
                except ValidationError as exc:
                    avatar_form.add_error("photo", exc)
                else:
                    _log(request, "profile_photo_updated")
                    messages.success(request, "Su foto de perfil se actualizó.")
                    return redirect("account_profile")
        elif section == "avatar_remove":
            if user.avatar:
                remove_avatar(user)
                _log(request, "profile_photo_removed")
                messages.success(request, "Se quitó su foto de perfil.")
            return redirect("account_profile")
        elif section == "preferences":
            preferences_form = PreferencesForm(request.POST, instance=user, prefix="preferences")
            if preferences_form.is_valid():
                preferences_form.save()
                messages.success(request, "Preferencia guardada.")
                return redirect(f"{reverse('account_profile')}#preferencias")
        else:
            return redirect("account_profile")
    return render(request, "registration/profile.html", {
        "personal_form": personal_form,
        "avatar_form": avatar_form,
        "preferences_form": preferences_form,
        "summary": role_summary(user),
        "security": security_summary(request),
        "support_url": reverse("institution_technical_support") if user.role == User.Role.INSTITUTION else "",
    })


@login_required
@require_POST
def close_other_sessions(request):
    closed = close_user_sessions(request.user, keep_session_key=request.session.session_key)
    _log(request, "other_sessions_closed", {"closed": closed})
    if closed:
        messages.success(request, f"Se cerraron {closed} sesión{'es' if closed != 1 else ''} en otros dispositivos.")
    else:
        messages.info(request, "No había otras sesiones abiertas.")
    return redirect(f"{reverse('account_profile')}#seguridad")


@login_required
@require_GET
def user_avatar(request, pk):
    person = get_object_or_404(User, pk=pk)
    if not user_can_view_avatar(request.user, person):
        raise PermissionDenied("No puede ver esta foto.")
    if not person.avatar:
        raise Http404("Sin foto.")
    try:
        file = person.avatar.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("Sin foto.") from exc
    response = FileResponse(file, content_type="image/jpeg")
    # La URL lleva la versión (?v=): cuando cambia la foto, cambia la dirección.
    response["Cache-Control"] = "private, max-age=86400"
    response["Content-Disposition"] = "inline"
    return response
