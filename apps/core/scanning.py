"""Análisis por INSTREAM: no expone rutas locales al servicio antivirus."""
import logging
import socket
import struct
import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse, HttpResponse

logger = logging.getLogger(__name__)


def scan_file(file):
    if not settings.FILE_SCAN_REQUIRED:
        return
    position = file.tell()
    deadline = time.monotonic() + settings.CLAMAV_TIMEOUT
    try:
        file.seek(0)
        with socket.create_connection(
            (settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=settings.CLAMAV_TIMEOUT
        ) as connection:
            def send(data):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                connection.settimeout(remaining)
                connection.sendall(data)

            send(b"zINSTREAM\0")
            total = 0
            while chunk := file.read(64 * 1024):
                total += len(chunk)
                if total > settings.FILE_MAX_UPLOAD_MB * 1024 * 1024:
                    raise ValidationError("El archivo supera el tamaño permitido.")
                send(struct.pack("!I", len(chunk)) + chunk)
            send(struct.pack("!I", 0))
            reply = b""
            while b"\0" not in reply and len(reply) < 4096:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                connection.settimeout(remaining)
                part = connection.recv(4096 - len(reply))
                if not part:
                    break
                reply += part
            if reply == b"stream: OK\0":
                return
            if reply.endswith(b" FOUND\0"):
                logger.warning("Antivirus rechazó un archivo.")
                raise ValidationError("El antivirus rechazó el archivo. No se permite su uso.")
            raise OSError("Respuesta de antivirus no concluyente")
    except OSError as exc:
        logger.error("Servicio antivirus no disponible o respuesta no concluyente.")
        raise ValidationError(
            "No se pudo verificar el archivo. Intente nuevamente más tarde."
        ) from exc
    finally:
        file.seek(position)


def protected_file_response(file, **kwargs):
    """Se invoca después de autorizar; también protege archivos históricos."""
    try:
        scan_file(file)
    except ValidationError:
        file.close()
        response = HttpResponse(
            "El archivo no está disponible: no pasó la verificación de seguridad.",
            status=503, content_type="text/plain; charset=utf-8",
        )
        response["Retry-After"] = "60"
    else:
        response = FileResponse(file, **kwargs)
    response["Cache-Control"] = "private, no-store"
    return response
