"""Contrasta los archivos registrados en la base de datos con el almacenamiento privado."""
import hashlib
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.management.base import BaseCommand, CommandError
from django.db import models


def file_fields():
    for model in apps.get_models():
        fields = [field for field in model._meta.concrete_fields if isinstance(field, models.FileField)]
        for field in fields:
            yield model, field, len(fields) == 1


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = (
        "Verifica que cada archivo registrado exista y conserve su tamaño; con --checksums "
        "recalcula su huella SHA-256. Informa archivos sin registro, sin eliminarlos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--checksums", action="store_true",
            help="Recalcula la huella SHA-256 de cada archivo que la tenga registrada (lento).",
        )

    def handle(self, *args, checksums=False, **options):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        if not media_root.is_dir():
            raise CommandError(f"No existe el almacenamiento privado {media_root}.")
        referenced = set()
        problems = []
        checked = without_digest = 0

        for model, field, owns_metadata in file_fields():
            concrete = {item.name for item in model._meta.concrete_fields}
            # El tamaño y la huella describen el archivo solo si el modelo tiene uno.
            has_size = owns_metadata and "size" in concrete
            has_digest = owns_metadata and "sha256" in concrete
            columns = ["pk", field.name, *(["size"] if has_size else []), *(["sha256"] if has_digest else [])]
            rows = model._default_manager.exclude(**{field.name: ""}).values_list(*columns)
            for row in rows.iterator():
                values = dict(zip(columns, row))
                name = values[field.name]
                label = f"{model._meta.label} #{values['pk']} ({field.name})"
                try:
                    path = Path(field.storage.path(name)).resolve()
                except SuspiciousFileOperation:
                    problems.append(f"{label}: ruta no válida «{name}».")
                    continue
                referenced.add(path)
                checked += 1
                if not path.is_file():
                    problems.append(f"{label}: falta el archivo {name}.")
                    continue
                # Los registros anteriores a estas columnas tienen 0 y huella vacía.
                expected_size = values.get("size") or 0
                if expected_size and path.stat().st_size != expected_size:
                    problems.append(
                        f"{label}: el tamaño de {name} es {path.stat().st_size} y se registró {expected_size}."
                    )
                    continue
                if checksums:
                    expected_digest = values.get("sha256") or ""
                    if not expected_digest:
                        without_digest += 1
                    elif sha256_of(path) != expected_digest:
                        problems.append(f"{label}: la huella SHA-256 de {name} no coincide con la registrada.")

        orphans = sorted(
            path for path in media_root.rglob("*")
            if path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(media_root).parts)
            and path.resolve() not in referenced
        )

        self.stdout.write(f"Archivos registrados revisados: {checked}.")
        if checksums:
            self.stdout.write(f"Archivos sin huella registrada (solo se comprobó su tamaño): {without_digest}.")
        if orphans:
            self.stdout.write(self.style.WARNING(
                f"Archivos sin registro en la base de datos: {len(orphans)}. No se eliminaron."
            ))
            for path in orphans:
                self.stdout.write(f"  {path.relative_to(media_root).as_posix()}")
        for problem in problems:
            self.stderr.write(problem)
        if problems:
            raise CommandError(
                f"Se encontraron {len(problems)} problemas de integridad. Restaure los archivos afectados desde el respaldo."
            )
        self.stdout.write(self.style.SUCCESS("Almacenamiento privado íntegro."))
