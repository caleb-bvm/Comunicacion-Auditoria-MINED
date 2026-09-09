from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.accounts.views import AccountProfileView, ActivateAccountView, RequiredPasswordChangeView


urlpatterns = [
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
    path("cambiar-contrasena/", RequiredPasswordChangeView.as_view(), name="password_change"),
    path("mi-perfil/", AccountProfileView.as_view(), name="account_profile"),
    path("activar-cuenta/<uidb64>/<token>/", ActivateAccountView.as_view(), name="activate_account"),
    path("cde/", include("apps.institutions.urls")),
    path("", include("apps.audits.urls")),
]
