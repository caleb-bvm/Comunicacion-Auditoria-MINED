from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.audits.models import ActivityLog, Evidence
from apps.institutions.models import Organization

from .forms import TechnicalSupportResolutionForm
from .models import TechnicalSupportRequest, User
from .security import close_user_sessions


def require_technical_admin(user):
    if not user.is_authenticated or not (user.is_superuser or user.role == User.Role.TECHNICAL_ADMIN):
        raise PermissionDenied("Esta sección corresponde a la administración técnica.")


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def record(request, action, target=None, details=None):
    ActivityLog.objects.create(
        actor=request.user,
        action=action,
        target_type=target.__class__.__name__ if target else "",
        target_id=str(target.pk) if target else "",
        details=details or {},
        ip_address=client_ip(request),
    )


class InternalUserForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña temporal", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)
    reason = forms.CharField(label="Motivo de creación", widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "job_title", "role", "organization")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = (
            (User.Role.TECHNICAL_ADMIN, User.Role.TECHNICAL_ADMIN.label),
            (User.Role.AUDITOR, User.Role.AUDITOR.label),
        )
        self.fields["organization"].queryset = Organization.objects.filter(is_active=True).order_by("name")
        self.fields["organization"].required = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif cleaned.get("password1"):
            validate_password(cleaned["password1"], self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.must_change_password = True
        user.is_staff = False
        if commit:
            user.save()
            self.save_m2m()
        return user


class TechnicalActionForm(forms.Form):
    reason = forms.CharField(
        label="Motivo",
        min_length=10,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Explique por qué se realiza esta acción."}),
    )


@login_required
def technical_dashboard(request):
    require_technical_admin(request.user)
    database_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        database_ok = False

    support_requests = TechnicalSupportRequest.objects.select_related(
        "organization", "requested_by"
    )
    open_requests = support_requests.filter(
        status__in=[TechnicalSupportRequest.Status.OPEN, TechnicalSupportRequest.Status.IN_PROGRESS]
    )
    context = {
        "active_users": User.objects.filter(is_active=True).count(),
        "inactive_users": User.objects.filter(is_active=False).count(),
        "forced_password_changes": User.objects.filter(is_active=True, must_change_password=True).count(),
        "pending_scans": Evidence.objects.filter(scan_status=Evidence.ScanStatus.PENDING).count(),
        "database_ok": database_ok,
        "recent_activity": ActivityLog.objects.select_related("actor")[:10],
        "open_support_requests": open_requests.count(),
        "new_support_requests": open_requests.filter(
            status=TechnicalSupportRequest.Status.OPEN
        ).count(),
        "support_in_progress": open_requests.filter(
            status=TechnicalSupportRequest.Status.IN_PROGRESS
        ).count(),
        "support_queue": open_requests.order_by("created_at")[:6],
    }
    return render(request, "technical/dashboard.html", context)


@login_required
def technical_user_list(request):
    require_technical_admin(request.user)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    role = request.GET.get("role", "")
    users = User.objects.select_related("organization").order_by("username")
    if query:
        users = users.filter(
            Q(username__icontains=query) | Q(first_name__icontains=query)
            | Q(last_name__icontains=query) | Q(email__icontains=query)
            | Q(organization__name__icontains=query)
        )
    if status == "active":
        users = users.filter(is_active=True)
    elif status == "inactive":
        users = users.filter(is_active=False)
    if role in User.Role.values:
        users = users.filter(role=role)
    return render(request, "technical/user_list.html", {
        "page_obj": Paginator(users, 30).get_page(request.GET.get("page")),
        "query": query, "status_filter": status, "role_filter": role, "roles": User.Role.choices,
    })


@login_required
@require_http_methods(["GET", "POST"])
def technical_user_create(request):
    require_technical_admin(request.user)
    form = InternalUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        record(request, "technical_user_created", user, {
            "username": user.username, "role": user.role, "reason": form.cleaned_data["reason"]
        })
        messages.success(request, "La cuenta fue creada y deberá cambiar su contraseña al ingresar.")
        return redirect("technical_user_detail", pk=user.pk)
    return render(request, "technical/user_form.html", {"form": form})


@login_required
def technical_user_detail(request, pk):
    require_technical_admin(request.user)
    user = get_object_or_404(User.objects.select_related("organization"), pk=pk)
    history = ActivityLog.objects.filter(target_type="User", target_id=str(user.pk)).select_related("actor")[:30]
    return render(request, "technical/user_detail.html", {
        "managed_user": user, "history": history, "action_form": TechnicalActionForm()
    })


@login_required
@require_POST
def technical_user_action(request, pk, action):
    require_technical_admin(request.user)
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser:
        raise PermissionDenied("Los superusuarios solo pueden administrarse por el procedimiento de emergencia.")
    if user.pk == request.user.pk and action in {"suspend", "sessions"}:
        raise PermissionDenied("No puede suspender su propia cuenta ni cerrar su sesión desde esta operación.")
    form = TechnicalActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indique un motivo de al menos 10 caracteres.")
        return redirect("technical_user_detail", pk=user.pk)

    before = {"is_active": user.is_active, "must_change_password": user.must_change_password}
    if action == "suspend":
        user.is_active = False
        user.save(update_fields=["is_active"])
        close_user_sessions(user)
        label = "suspendida"
    elif action == "reactivate":
        user.is_active = True
        user.save(update_fields=["is_active"])
        label = "reactivada"
    elif action == "force-password":
        user.must_change_password = True
        user.save(update_fields=["must_change_password"])
        close_user_sessions(user)
        label = "marcada para cambio de contraseña"
    elif action == "sessions":
        close_user_sessions(user)
        label = "desconectada de todas sus sesiones"
    else:
        raise PermissionDenied("Acción administrativa no reconocida.")
    record(request, f"technical_user_{action.replace('-', '_')}", user, {
        "username": user.username, "reason": form.cleaned_data["reason"], "before": before,
        "after": {"is_active": user.is_active, "must_change_password": user.must_change_password},
    })
    messages.success(request, f"La cuenta fue {label}.")
    return redirect("technical_user_detail", pk=user.pk)


@login_required
def technical_activity_log(request):
    require_technical_admin(request.user)
    query = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    logs = ActivityLog.objects.select_related("actor").order_by("-created_at")
    if query:
        logs = logs.filter(
            Q(actor__username__icontains=query) | Q(target_id__icontains=query)
            | Q(target_type__icontains=query) | Q(action__icontains=query)
        )
    if action:
        logs = logs.filter(action=action)
    actions = ActivityLog.objects.order_by("action").values_list("action", flat=True).distinct()
    return render(request, "technical/activity_log.html", {
        "page_obj": Paginator(logs, 50).get_page(request.GET.get("page")),
        "query": query, "action_filter": action, "actions": actions,
    })


@login_required
@require_http_methods(["GET", "POST"])
def technical_support_requests(request, pk=None):
    require_technical_admin(request.user)
    selected = None
    form = None
    if pk is not None:
        selected = get_object_or_404(
            TechnicalSupportRequest.objects.select_related("organization", "requested_by", "handled_by"),
            pk=pk,
        )
        form = TechnicalSupportResolutionForm(request.POST or None, initial={"status": selected.status})
        if request.method == "POST" and form.is_valid():
            before = selected.status
            selected.status = form.cleaned_data["status"]
            selected.resolution = form.cleaned_data["resolution"]
            selected.handled_by = request.user
            selected.resolved_at = (
                timezone.now()
                if selected.status in {TechnicalSupportRequest.Status.RESOLVED, TechnicalSupportRequest.Status.CLOSED}
                else None
            )
            selected.save(update_fields=[
                "status", "resolution", "handled_by", "resolved_at", "updated_at"
            ])
            record(request, "technical_support_updated", selected, {
                "before": before, "after": selected.status,
                "requester": (
                    selected.requested_by.username
                    if selected.requested_by else selected.requester_identifier
                ),
            })
            messages.success(request, "La solicitud técnica fue actualizada.")
            return redirect("technical_support_request_detail", pk=selected.pk)
    status = request.GET.get("status", "")
    category = request.GET.get("category", "")
    all_requests = TechnicalSupportRequest.objects.all()
    requests = TechnicalSupportRequest.objects.select_related(
        "organization", "requested_by", "handled_by"
    )
    if status in TechnicalSupportRequest.Status.values:
        requests = requests.filter(status=status)
    if category in TechnicalSupportRequest.Category.values:
        requests = requests.filter(category=category)
    return render(request, "technical/support_requests.html", {
        "support_requests": requests, "selected": selected, "form": form,
        "status_filter": status, "statuses": TechnicalSupportRequest.Status.choices,
        "category_filter": category, "categories": TechnicalSupportRequest.Category.choices,
        "support_counts": {
            "all": all_requests.count(),
            "open": all_requests.filter(status=TechnicalSupportRequest.Status.OPEN).count(),
            "in_progress": all_requests.filter(status=TechnicalSupportRequest.Status.IN_PROGRESS).count(),
            "resolved": all_requests.filter(status=TechnicalSupportRequest.Status.RESOLVED).count(),
            "closed": all_requests.filter(status=TechnicalSupportRequest.Status.CLOSED).count(),
        },
    })
