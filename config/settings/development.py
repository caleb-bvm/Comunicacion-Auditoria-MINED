import os

from .base import *


def load_local_environment(path):
    """Carga ajustes locales sin sobrescribir variables ya definidas."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_environment(BASE_DIR / ".env.development")


DEBUG = True
SECRET_KEY = "solo-desarrollo-no-usar-en-produccion-cambiar-antes-de-publicar"
ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "testserver",
    *env_list("DJANGO_ALLOWED_HOSTS"),
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "endpoint_dev"),
        "USER": os.getenv("POSTGRES_USER", "endpoint_app"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
FILE_SCAN_REQUIRED = False
# Las pruebas de seguridad activan Axes explícitamente; producción lo exige.
AXES_ENABLED = False
ALLOW_DEMO_DATA = True
