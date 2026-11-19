from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.profile import account_profile, close_other_sessions, user_avatar
from apps.accounts.views import (
    ActivateAccountView, RequiredPasswordChangeView,
    SecurePasswordResetConfirmView, institution_technical_support,
    password_reset_request, password_support_request,
)
from apps.core.views import offline_page, service_worker, ui_reference
from apps.institutions.search import organization_search


class FaviconRedirectView(RedirectView):
    # Resolved per request so ManifestStaticFilesStorage hashes are read lazily.
    def get_redirect_url(self, *args, **kwargs):
        return static("img/favicon.ico")


urlpatterns = [
    # Browsers request /favicon.ico on their own (PDF downloads, bookmarks).
    path("favicon.ico", FaviconRedirectView.as_view()),
    path("sw.js", service_worker, name="service_worker"),
    path("sin-conexion/", offline_page, name="offline"),
    path("tecnica/", include("apps.accounts.technical_urls")),
    path("administracion/", admin.site.urls),
    path(
        "ingresar/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("soporte/restablecer-contrasena/", password_support_request, name="password_support_request"),
    path("restablecer-contrasena/", password_reset_request, name="password_reset_request"),
    path(
        "restablecer/<uidb64>/<token>/",
        SecurePasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("cambiar-contrasena/", RequiredPasswordChangeView.as_view(), name="password_change"),
    path("mi-perfil/", account_profile, name="account_profile"),
    path("mi-perfil/sesiones/cerrar/", close_other_sessions, name="account_close_other_sessions"),
    path("personas/<int:pk>/foto/", user_avatar, name="user_avatar"),
    path("mi-organizacion/soporte-tecnico/", institution_technical_support,
         name="institution_technical_support"),
    path("activar-cuenta/<uidb64>/<token>/", ActivateAccountView.as_view(), name="activate_account"),
    path("dev/ui/", ui_reference, name="ui_reference"),
    path("organizaciones/buscar/", organization_search, name="organization_search"),
    path("cde/", include("apps.institutions.urls")),
    path("", include("apps.audits.urls")),
]

handler400 = "apps.core.errors.bad_request"
handler403 = "apps.core.errors.permission_denied"
handler404 = "apps.core.errors.page_not_found"
handler500 = "apps.core.errors.server_error"
