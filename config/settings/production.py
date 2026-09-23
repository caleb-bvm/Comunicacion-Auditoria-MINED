import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .base import *


DEBUG = False
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 8 or SECRET_KEY.startswith(("solo-desarrollo", "django-insecure-")):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY debe existir y contener al menos 50 caracteres.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or any("*" in host or host.startswith(".") for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS es obligatorio en producción.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if any(not origin.startswith("https://") or "*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS solo admite orígenes HTTPS explícitos.")

public_url = urlsplit(PUBLIC_BASE_URL)
if (public_url.scheme != "https" or public_url.hostname not in ALLOWED_HOSTS
        or public_url.username or public_url.password or public_url.query
        or public_url.fragment or public_url.path not in {"", "/"}):
    raise ImproperlyConfigured("PUBLIC_BASE_URL debe ser el origen HTTPS de un dominio permitido.")
if not EMAIL_HOST or EMAIL_HOST == "localhost" or DEFAULT_FROM_EMAIL.endswith("@localhost"):
    raise ImproperlyConfigured("Configure el correo institucional antes de iniciar producción.")
if EMAIL_USE_TLS == EMAIL_USE_SSL:
    raise ImproperlyConfigured("Active exactamente una opción de cifrado SMTP: TLS o SSL.")

required_database_values = {
    "NAME": os.getenv("POSTGRES_DB"),
    "USER": os.getenv("POSTGRES_USER"),
    "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
    "HOST": os.getenv("POSTGRES_HOST"),
}
missing_database_values = [key for key, value in required_database_values.items() if not value]
if missing_database_values:
    raise ImproperlyConfigured(
        "Faltan ajustes de PostgreSQL: " + ", ".join(missing_database_values)
    )

database_sslmode = os.getenv("POSTGRES_SSLMODE", "verify-full")
if database_sslmode != "verify-full" and not (
    required_database_values["HOST"] in {"127.0.0.1", "::1", "localhost"}
    and database_sslmode == "disable"
):
    raise ImproperlyConfigured("PostgreSQL remoto requiere sslmode=verify-full; disable solo se admite en loopback.")
database_options = {"sslmode": database_sslmode, "connect_timeout": 10,
                    "options": "-c statement_timeout=60000 -c lock_timeout=10000"}
if os.getenv("POSTGRES_SSLROOTCERT"):
    database_options["sslrootcert"] = os.environ["POSTGRES_SSLROOTCERT"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        **required_database_values,
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": database_options,
    }
}

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", default=False)
FILE_SCAN_REQUIRED = env_bool("FILE_SCAN_REQUIRED", default=True)
if not FILE_SCAN_REQUIRED:
    raise ImproperlyConfigured("El análisis antivirus es obligatorio en producción.")
AXES_ENABLED = True
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"
MEDIA_ROOT = Path(os.environ.get("PRIVATE_MEDIA_ROOT", "/var/lib/siga-mineducyt/private"))
if not MEDIA_ROOT.is_absolute() or MEDIA_ROOT == STATIC_ROOT or STATIC_ROOT in MEDIA_ROOT.parents:
    raise ImproperlyConfigured("PRIVATE_MEDIA_ROOT debe ser absoluto y estar fuera de archivos públicos.")
