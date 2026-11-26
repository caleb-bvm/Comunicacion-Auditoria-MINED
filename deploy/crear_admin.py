"""Crea la primera cuenta de administración técnica (lo usan los instaladores
deploy/instalar-servidor.sh y deploy/windows/instalar-servidor.ps1).

  python crear_admin.py existe   -> código 0 si ya hay una cuenta technical_admin activa
  python crear_admin.py crear    -> crea la cuenta con las variables SIGA_ADMIN_*

La contraseña llega por SIGA_ADMIN_PASSWORD o, si falta, por la primera línea de la
entrada estándar, para no aparecer en la línea de comandos.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

import django  # noqa: E402

django.setup()

from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.db import transaction  # noqa: E402

from apps.accounts.models import User  # noqa: E402


def admin_exists():
    return User.objects.filter(role=User.Role.TECHNICAL_ADMIN, is_active=True).exists()


def create_admin():
    username = os.environ["SIGA_ADMIN_USERNAME"].strip()
    if User.objects.filter(username__iexact=username).exists():
        print(f"Ya existe un usuario llamado {username}.")
        return 2
    user = User(
        username=username,
        email=os.environ.get("SIGA_ADMIN_EMAIL", "").strip(),
        first_name=os.environ.get("SIGA_ADMIN_FIRST_NAME", "").strip(),
        last_name=os.environ.get("SIGA_ADMIN_LAST_NAME", "").strip(),
        role=User.Role.TECHNICAL_ADMIN,
        is_staff=True,
        is_superuser=True,
        # La persona que instala elige su propia contraseña; no es temporal.
        must_change_password=False,
    )
    password = os.environ.get("SIGA_ADMIN_PASSWORD") or sys.stdin.readline().rstrip("\r\n")
    try:
        validate_password(password, user)
    except ValidationError as exc:
        for message in exc.messages:
            print(message)
        return 3
    user.set_password(password)
    with transaction.atomic():
        user.full_clean(exclude=["password"])
        user.save()
    print(f"Cuenta de administración técnica creada: {username}")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "existe":
        sys.exit(0 if admin_exists() else 1)
    if action == "crear":
        sys.exit(create_admin())
    print("Uso: crear_admin.py existe|crear")
    sys.exit(64)
