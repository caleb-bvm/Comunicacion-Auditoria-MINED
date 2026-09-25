import hashlib
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordChangeView
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.core.exceptions import PermissionDenied
from django.urls import reverse, reverse_lazy

from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .activation import activation_token_generator
from .forms import (
    InstitutionTechnicalSupportRequestForm, PasswordResetRequestForm,
    PublicPasswordSupportRequestForm,
)
from .models import TechnicalSupportRequest, User
from .security import client_ip, close_user_sessions


class AccountProfileView(LoginRequiredMixin, TemplateView):
    template_name = "registration/profile.html"


@require_http_methods(["GET", "POST"])
def institution_technical_support(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.path}")
    if request.user.role != User.Role.INSTITUTION or not request.user.organization_id:
        raise PermissionDenied("Esta sección corresponde a las organizaciones registradas.")
    form = InstitutionTechnicalSupportRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        support_request = form.save(commit=False)
        support_request.organization = request.user.organization
        support_request.requested_by = request.user
        support_request.save()
        from apps.audits.models import ActivityLog
        ActivityLog.objects.create(
            actor=request.user, action="technical_support_requested",
            target_type="TechnicalSupportRequest", target_id=str(support_request.pk),
            details={
                "category": support_request.category,
                "subject": support_request.subject,
                "organization_id": request.user.organization_id,
            },
            ip_address=client_ip(request),
        )
        messages.success(request, "La solicitud fue enviada a Administración Técnica.")
        return redirect("institution_technical_support")
    support_requests = TechnicalSupportRequest.objects.filter(
        requested_by=request.user,
    ).select_related("handled_by")
    return render(request, "registration/institution_technical_support.html", {
        "form": form,
        "support_requests": support_requests,
    })


@require_http_methods(["GET", "POST"])
def password_support_request(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = PublicPasswordSupportRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        last_request = request.session.get("password_support_requested_at")
        now = timezone.now()
        if not last_request or now.timestamp() - last_request >= 60:
            identifier = form.cleaned_data["identifier"].strip()
            category = form.cleaned_data["category"]
            category_labels = dict(TechnicalSupportRequest.Category.choices)
            user = User.objects.filter(
                Q(username__iexact=identifier) | Q(email__iexact=identifier)
            ).select_related("organization").first()
            support_request = TechnicalSupportRequest.objects.create(
                category=category,
                subject=f"Solicitud de soporte: {category_labels[category]}",
                description=form.cleaned_data["description"],
                organization=user.organization if user else None,
                requested_by=user,
                requester_name=form.cleaned_data["full_name"],
                requester_identifier=identifier,
                requester_contact=form.cleaned_data["contact_email"],
                is_public_request=True,
            )
            from apps.audits.models import ActivityLog
            ActivityLog.objects.create(
                actor=None, action="public_password_support_requested",
                target_type="TechnicalSupportRequest", target_id=str(support_request.pk),
                details={"account_matched": user is not None},
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            request.session["password_support_requested_at"] = now.timestamp()
        return render(request, "registration/password_support_requested.html", status=202)
    return render(request, "registration/password_support_request.html", {"form": form})


def _public_origin(request):
    origin = settings.PUBLIC_BASE_URL.rstrip("/")
    if not origin and settings.DEBUG:
        origin = request.build_absolute_uri("/").rstrip("/")
    parsed = urlsplit(origin)
    allowed_schemes = {"http", "https"} if settings.DEBUG else {"https"}
    if (not parsed.netloc or parsed.scheme not in allowed_schemes or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValidationError("La dirección pública del sistema no está configurada correctamente.")
    return origin


def _reset_request_allowed(request, identifier):
    """Apply complementary limits without storing the submitted identifier in cache keys."""
    digest = hashlib.sha256(identifier.casefold().encode()).hexdigest()
    ip_digest = hashlib.sha256((client_ip(request) or "unknown").encode()).hexdigest()
    window = 15 * 60
    allowed = True
    for key, limit in ((f"password-reset:user:{digest}", 3), (f"password-reset:ip:{ip_digest}", 10)):
        if cache.add(key, 1, window):
            continue
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)
            count = 1
        allowed = allowed and count <= limit
    return allowed


@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        identifier = form.cleaned_data["identifier"].strip()
        if _reset_request_allowed(request, identifier):
            matches = list(User.objects.filter(
                Q(username__iexact=identifier) | Q(email__iexact=identifier),
                is_active=True,
            ).exclude(email="")[:2])
            user = matches[0] if len(matches) == 1 else None
            if user:
                path = reverse("password_reset_confirm", kwargs={
                    "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                    "token": default_token_generator.make_token(user),
                })
                try:
                    hours = max(1, settings.PASSWORD_RESET_TIMEOUT // 3600)
                    sent = send_mail(
                        "Restablecimiento de contraseña | SIGA-MINEDUCYT",
                        "Se solicitó restablecer la contraseña de su cuenta.\n\n"
                        f"Utilice este enlace durante la próxima {hours} hora(s):\n"
                        f"{_public_origin(request)}{path}\n\n"
                        "El enlace solo puede utilizarse una vez. Si no realizó esta solicitud, "
                        "ignore este mensaje; su contraseña no ha cambiado.",
                        settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
                    )
                except Exception:
                    sent = 0
                if sent == 1:
                    from apps.audits.models import ActivityLog
                    ActivityLog.objects.create(
                        actor=None, action="password_reset_email_sent",
                        target_type="User", target_id=str(user.pk),
                        details={"username": user.username}, ip_address=client_ip(request),
                    )
        return render(request, "registration/password_reset_requested.html", status=202)
    return render(request, "registration/password_reset_request.html", {"form": form})


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters(), name="dispatch")
class SecurePasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        user = form.user
        response = super().form_valid(form)
        if user.must_change_password:
            user.must_change_password = False
            user.save(update_fields=["must_change_password"])
        close_user_sessions(user)
        from apps.audits.models import ActivityLog
        ActivityLog.objects.create(
            actor=user, action="password_reset_completed", target_type="User",
            target_id=str(user.pk), details={"username": user.username},
            ip_address=client_ip(self.request),
        )
        messages.success(self.request, "La contraseña fue actualizada. Ya puede iniciar sesión.")
        return response


class RequiredPasswordChangeView(PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters(), name="dispatch")
class ActivateAccountView(View):
    template_name = "registration/activate_account.html"

    def account(self, uidb64, *, lock=False):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            query = User.objects.select_related("organization")
            if lock:
                query = query.select_for_update(of=("self",))
            return query.get(pk=uid, role=User.Role.INSTITUTION)
        except (ValueError, TypeError, OverflowError, UnicodeDecodeError, User.DoesNotExist):
            return None

    def display(self, request, *, account=None, form=None):
        response = render(request, self.template_name, {
            "validlink": account is not None,
            "account": account,
            "form": form,
        })
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def get(self, request, uidb64, token):
        account = self.account(uidb64)
        session_key = f"center_activation_{uidb64}"
        if token != "establecer":
            if activation_token_generator.check_token(account, token):
                # Keep the secret out of the form URL and subsequent referrers.
                request.session[session_key] = token
                response = redirect("activate_account", uidb64=uidb64, token="establecer")
                response.headers["Referrer-Policy"] = "no-referrer"
                return response
            return self.display(request)
        if not activation_token_generator.check_token(account, request.session.get(session_key)):
            return self.display(request)
        return self.display(request, account=account, form=SetPasswordForm(account))

    def post(self, request, uidb64, token):
        from apps.audits.models import ActivityLog

        session_key = f"center_activation_{uidb64}"
        with transaction.atomic():
            account = self.account(uidb64, lock=True)
            if token != "establecer" or not activation_token_generator.check_token(
                account, request.session.get(session_key)
            ):
                return self.display(request)
            form = SetPasswordForm(account, request.POST)
            if not form.is_valid():
                return self.display(request, account=account, form=form)
            account = form.save(commit=False)
            account.is_active = True
            account.must_change_password = False
            account.activation_requested_at = None
            account.save(update_fields=[
                "password", "is_active", "must_change_password", "activation_requested_at"
            ])
            ActivityLog.objects.create(
                actor=account, action="educational_center_activated",
                target_type="Organization", target_id=str(account.organization_id),
                details={"institutional_user_id": account.pk, "username": account.username},
            )
        request.session.pop(session_key, None)
        messages.success(request, "Acceso activado. Ingrese con el código del centro y su nueva contraseña.")
        return redirect("login")
