import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.institutions.models import Organization


TRUE_VALUES = {"1", "true", "yes", "si", "sí", "activo", "active"}
FALSE_VALUES = {"0", "false", "no", "inactivo", "inactive"}


class Command(BaseCommand):
    help = "Importa o actualiza el catálogo institucional desde un archivo CSV UTF-8."

    def add_arguments(self, parser):
        parser.add_argument("csv_file", help="Ruta del archivo CSV que contiene el catálogo.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida y muestra el resultado esperado sin guardar cambios.",
        )

    def handle(self, *args, **options):
        source = Path(options["csv_file"])
        if not source.is_file():
            raise CommandError(f"No se encontró el archivo: {source}")

        rows = self.read_rows(source)
        existing = Organization.objects.in_bulk(field_name="code")
        created = 0
        updated = 0
        unchanged = 0

        with transaction.atomic():
            for row in rows:
                code = row["code"]
                defaults = {key: value for key, value in row.items() if key != "code"}
                current = existing.get(code)
                if current is None:
                    created += 1
                elif any(getattr(current, key) != value for key, value in defaults.items()):
                    updated += 1
                else:
                    unchanged += 1

                if not options["dry_run"]:
                    Organization.objects.update_or_create(code=code, defaults=defaults)

        mode = "SIMULACIÓN" if options["dry_run"] else "IMPORTACIÓN"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} completada: {created} nuevas, {updated} actualizadas, "
                f"{unchanged} sin cambios."
            )
        )

    def read_rows(self, source):
        try:
            handle = source.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise CommandError(f"No fue posible abrir el archivo: {exc}") from exc

        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"code", "name"}.issubset(reader.fieldnames):
                raise CommandError("El CSV debe incluir como mínimo las columnas code y name.")
            includes_district = "district" in reader.fieldnames
            center_type_field = next(
                (
                    field
                    for field in (
                        "educational_center_type",
                        "center_type",
                        "tipo_centro",
                    )
                    if field in reader.fieldnames
                ),
                None,
            )
            rows = []
            seen_codes = set()
            valid_kinds = set(Organization.Kind.values)
            for line_number, raw in enumerate(reader, start=2):
                code = (raw.get("code") or "").strip()
                name = (raw.get("name") or "").strip()
                kind = (raw.get("kind") or Organization.Kind.EDUCATIONAL_CENTER).strip()
                if not code or not name:
                    raise CommandError(f"Fila {line_number}: code y name son obligatorios.")
                if code in seen_codes:
                    raise CommandError(f"Fila {line_number}: el código {code} está repetido.")
                if kind not in valid_kinds:
                    raise CommandError(
                        f"Fila {line_number}: tipo inválido. Use uno de: {', '.join(sorted(valid_kinds))}."
                    )
                seen_codes.add(code)
                row = {
                    "code": code,
                    "name": name,
                    "kind": kind,
                    "department": (raw.get("department") or "").strip(),
                    "municipality": (raw.get("municipality") or "").strip(),
                    "address": (raw.get("address") or "").strip(),
                    "is_active": self.parse_active(raw.get("is_active"), line_number),
                }
                if includes_district:
                    row["district"] = (raw.get("district") or "").strip()
                if center_type_field:
                    row["educational_center_type"] = (
                        raw.get(center_type_field) or ""
                    ).strip()
                rows.append(row)
            return rows

    def parse_active(self, value, line_number):
        normalized = (value or "true").strip().lower()
        if normalized in TRUE_VALUES:
            return True
        if normalized in FALSE_VALUES:
            return False
        raise CommandError(
            f"Fila {line_number}: is_active debe indicar true/false, sí/no o activo/inactivo."
        )
