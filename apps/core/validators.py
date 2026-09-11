import zipfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from .scanning import scan_file


ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"}


def validate_evidence_file(uploaded_file):
    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("Formato no permitido. Use PDF, JPG, PNG, DOCX o XLSX.")

    maximum = settings.FILE_MAX_UPLOAD_MB * 1024 * 1024
    if uploaded_file.size > maximum:
        raise ValidationError(f"El archivo supera el máximo de {settings.FILE_MAX_UPLOAD_MB} MB.")

    position = uploaded_file.tell()
    try:
        header = uploaded_file.read(12)
        uploaded_file.seek(0)
        if extension == ".pdf" and not header.startswith(b"%PDF-"):
            raise ValidationError("El contenido no corresponde a un archivo PDF válido.")
        if extension in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
            raise ValidationError("El contenido no corresponde a una imagen JPEG válida.")
        if extension == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationError("El contenido no corresponde a una imagen PNG válida.")
        if extension in {".docx", ".xlsx"}:
            if not header.startswith(b"PK"):
                raise ValidationError("El documento de Office no tiene una estructura válida.")
            try:
                with zipfile.ZipFile(uploaded_file) as archive:
                    members = archive.infolist()
                    if len(members) > 5000:
                        raise ValidationError("El documento contiene demasiados elementos internos.")
                    expanded_size = sum(member.file_size for member in members)
                    if expanded_size > maximum * 5:
                        raise ValidationError("El contenido expandido del documento es demasiado grande.")
                    names = {member.filename for member in members}
                    expected_prefix = "word/" if extension == ".docx" else "xl/"
                    if "[Content_Types].xml" not in names or not any(
                        name.startswith(expected_prefix) for name in names
                    ):
                        raise ValidationError("El contenido no corresponde al tipo de documento indicado.")
            except zipfile.BadZipFile as exc:
                raise ValidationError("El documento de Office está dañado o no es válido.") from exc
    finally:
        uploaded_file.seek(position)
    scan_file(uploaded_file)
