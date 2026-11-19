from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Cuentas"


    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from .signals import record_login

        user_logged_in.connect(record_login, dispatch_uid="accounts_record_login")
