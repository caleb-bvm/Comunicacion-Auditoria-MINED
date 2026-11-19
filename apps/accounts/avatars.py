"""Fotos de perfil: validación, recodificación y control de acceso.

La imagen recibida se analiza con el antivirus y después se vuelve a dibujar con
Pillow como un JPEG cuadrado nuevo, sin metadatos (EXIF, GPS ni perfiles). El
archivo guardado lo genera el servidor, por eso se sirve sin volver a analizarlo
en cada vista: una página con veinte personas haría veinte análisis.
"""
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.core.scanning import scan_file

AVATAR_PIXELS = 384
AVATAR_MAX_MB = 5
AVATAR_MAX_SOURCE_PIXELS = 40_000_000
AVATAR_ACCEPT = "image/jpeg,image/png,.jpg,.jpeg,.png"
ALLOWED_FORMATS = {"JPEG", "PNG"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def process_avatar(uploaded_file):
    """Devuelve un ContentFile JPEG de 384×384 o lanza ValidationError."""
    if Path(uploaded_file.name or "").suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError("Use una foto JPG o PNG.")
    if uploaded_file.size > AVATAR_MAX_MB * 1024 * 1024:
        raise ValidationError(f"La foto supera el máximo de {AVATAR_MAX_MB} MB.")
    scan_file(uploaded_file)
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise ValidationError("Use una foto JPG o PNG.")
            width, height = probe.size
            if width * height > AVATAR_MAX_SOURCE_PIXELS:
                raise ValidationError("La foto tiene una resolución demasiado grande.")
            probe.verify()
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in {"RGBA", "LA", "P"}:
                image = image.convert("RGBA")
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(
                image, (AVATAR_PIXELS, AVATAR_PIXELS), Image.Resampling.LANCZOS
            )
            output = BytesIO()
            image.save(output, format="JPEG", quality=86, optimize=True, progressive=True)
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError("No se pudo leer la foto. Pruebe con otra imagen.") from exc
    finally:
        uploaded_file.seek(0)
    return ContentFile(output.getvalue(), name="perfil.jpg")


def replace_avatar(user, uploaded_file):
    content = process_avatar(uploaded_file)
    previous = user.avatar.name if user.avatar else ""
    user.avatar.save(content.name, content, save=False)
    user.avatar_updated_at = timezone.now()
    user.save(update_fields=["avatar", "avatar_updated_at"])
    _delete_stored(user.avatar.storage, previous)


def remove_avatar(user):
    previous = user.avatar.name if user.avatar else ""
    user.avatar = ""
    user.avatar_updated_at = timezone.now()
    user.save(update_fields=["avatar", "avatar_updated_at"])
    _delete_stored(user.avatar.storage, previous)


def _delete_stored(storage, name):
    # La foto anterior es un dato personal sin valor de expediente: no se conserva.
    if name:
        try:
            storage.delete(name)
        except OSError:
            pass


def user_can_view_avatar(viewer, person):
    if not viewer.is_authenticated or not person.is_active:
        return viewer.is_authenticated and viewer.pk == person.pk
    if viewer.pk == person.pk:
        return True
    if viewer.is_superuser or viewer.role != viewer.Role.INSTITUTION:
        return True
    # Una institución solo ve a las personas de su propia organización: en las consultas
    # el personal de auditoría aparece como «Auditoría», sin nombre ni foto.
    return (
        person.role == person.Role.INSTITUTION and not person.is_superuser
        and bool(viewer.organization_id) and viewer.organization_id == person.organization_id
    )
