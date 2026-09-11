"""Pruebas sobre PostgreSQL efímero, sin credenciales ni datos de producción."""
from .development import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "endpoint_test",
        "USER": "endpoint_test",
        "PASSWORD": "test-only-ci-password",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}
