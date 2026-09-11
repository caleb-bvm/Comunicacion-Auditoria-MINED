from .base import *


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
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
FILE_SCAN_REQUIRED = False
# Las pruebas de seguridad activan Axes explícitamente; producción lo exige.
AXES_ENABLED = False
ALLOW_DEMO_DATA = True
