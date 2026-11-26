"""Prueba la conexión SMTP con las variables EMAIL_* antes de guardarlas.

Lo usan los instaladores de Linux y Windows; recibe los datos por variables de entorno para no
exponer la contraseña en la línea de comandos.
"""
import os
import smtplib
import ssl
import sys


def main():
    host = os.environ["EMAIL_HOST"]
    port = int(os.environ["EMAIL_PORT"])
    user = os.environ.get("EMAIL_HOST_USER", "")
    password = os.environ.get("EMAIL_HOST_PASSWORD", "")
    use_ssl = os.environ.get("EMAIL_USE_SSL", "false").lower() == "true"
    context = ssl.create_default_context()
    try:
        if use_ssl:
            connection = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        else:
            connection = smtplib.SMTP(host, port, timeout=15)
            connection.starttls(context=context)
        if user:
            connection.login(user, password)
        connection.quit()
    except smtplib.SMTPAuthenticationError:
        print("El servidor rechazó el usuario o la contraseña.")
        return 1
    except (OSError, smtplib.SMTPException) as exc:
        print(f"No se pudo conectar: {exc}")
        return 1
    print("Conexión SMTP correcta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
