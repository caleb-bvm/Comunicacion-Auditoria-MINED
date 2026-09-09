from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy

from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from .activation import activation_token_generator
from .models import User


class AccountProfileView(LoginRequiredMixin, TemplateView):
    template_name = "registration/profile.html"


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
