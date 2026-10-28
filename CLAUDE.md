# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proyecto

SIGA-MINEDUCYT: sistema Django 5.2 que comunica a la Dirección de Auditoría Interna del Ministerio de Educación de El Salvador con los centros educativos y las demás dependencias. Cubre expedientes, hallazgos, recomendaciones, respuestas institucionales con evidencias, revisión, aprobación directiva, informes anteriores, CDE, consultas y análisis territorial.

- La interfaz, la documentación (`docs/`) y los mensajes al usuario están en español. Los identificadores de código están en inglés. Los commits usan Conventional Commits en inglés (`feat:`, `fix:`, `test:`, `docs:`).
- Zona horaria `America/El_Salvador` e idioma `es-sv`. Las fechas de los tests deben compararse en la zona horaria de la aplicación, no en UTC.

## Comandos (Windows, PowerShell)

```powershell
.\iniciar.ps1                                   # migra y levanta runserver en 0.0.0.0:8000 (PC + teléfono en la misma red)
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py test apps.audits.test_inquiries                # un módulo
.\.venv\Scripts\python.exe manage.py test apps.audits.tests.SomeTestCase.test_name  # un test
.\.venv\Scripts\python.exe manage.py seed_demo [--reset-passwords]                  # datos demo (solo local)
```

- `manage.py` usa `config.settings.development` por defecto; `wsgi.py` usa `config.settings.production`.
- El desarrollo usa **PostgreSQL** (credenciales en `.env.development`, cargado por `development.py` sin sobrescribir variables existentes). SQLite ya no se usa.
- CI (`.github/workflows/security.yml`, rama `master`): `check`, `makemigrations --check`, `test` con `config.settings.ci` sobre Postgres 16 y `pip-audit`. Todo cambio debe pasar estos cuatro pasos.
- No hay linter ni formateador configurado.

## Configuración

`config/settings/`: `base.py` (común), `development.py` (DEBUG, clave fija, correo a consola, `FILE_SCAN_REQUIRED=False`, Axes desactivado, `ALLOW_DEMO_DATA=True`), `ci.py` (hereda de development con BD de prueba) y `production.py` (exige variables de entorno sin valores predeterminados; inventario en `.env.example`). Los tests de seguridad activan Axes explícitamente.

## Arquitectura

Cuatro apps en `apps/`:

- **accounts**: `User` personalizado (`AUTH_USER_MODEL`) con `Role`: `technical_admin`, `audit_manager` (Dirección), `auditor` e `institution` (vinculado a una `organization`). Incluye la activación por invitación (de un solo uso, vence a las 24 h; el usuario institucional es el código exacto del centro), `MustChangePasswordMiddleware` y el panel de soporte técnico (`technical.py`, `technical_urls.py`, plantillas en `templates/technical/`).
- **institutions**: catálogo de organizaciones y centros (departamento y distrito), CDE (períodos e integrantes, sin eliminación) y comandos de importación (`import_organizations`, `import_center_locations`, `import_center_emails --dry-run`).
- **audits**: el núcleo. `models.py` (AuditCase → Finding → Recommendation → respuestas/Evidence, AuditDocument, prórrogas, consultas, `ActivityLog`). `views.py` es un archivo grande (~3200 líneas) que concentra las vistas y los helpers de autorización. La lógica reutilizable está en `services.py` (días hábiles, plazo efectivo, vencimientos, copia de recomendaciones históricas), `statistics.py`, `territorial_analysis.py`, `center_analytics.py`, `historical_documents.py`, `historical_bulk.py` y los generadores `xlsx.py` y `pdf.py`.
- **core**: `scanning.py` (ClamAV con `scan_file` y `protected_file_response`), `validators.py` (extensión, tamaño, firma y estructura Office), `SecurityHeadersMiddleware` y `deployment_preflight`.

### Reglas transversales que hay que respetar

- **Autorización explícita por objeto.** El acceso se decide con helpers de `apps/audits/views.py` (`user_can_access_document`, `user_can_access_response`, `user_can_edit_case`, `require_director`, etc.), no con permisos de Django. Un auditor solo ve sus expedientes asignados; una institución solo ve lo propio o las recomendaciones asignadas a ella, y nunca los archivos de otra dependencia del mismo expediente. Un adjunto exige acceso a su `parent_report`. Cualquier vista o consulta nueva debe aplicar el mismo alcance.
- **Archivos privados.** Se guardan en `MEDIA_ROOT = media/private` con nombres aleatorios y se descargan siempre a través de `protected_file_response`, que vuelve a analizar el archivo después de comprobar permisos. Nunca deben exponerse con una URL directa.
- **Bitácora.** Las acciones relevantes (envíos, revisiones, descargas, cambios de visibilidad, reasignaciones) llaman a `log_activity(...)` → `ActivityLog`.
- **Nada se borra.** Los expedientes publicados, los CDE y los documentos no se eliminan; las correcciones crean versiones nuevas. Las decisiones de Dirección (publicar, cerrar, devolver, reasignar) requieren una justificación.
- **Plazos** en días hábiles, excluyendo fines de semana y asuetos activos, respetando la última prórroga (`services.with_effective_deadline`). `process_overdue_recommendations` marca diariamente como no cumplidas las recomendaciones vencidas.
- **Análisis territorial**: la web y el XLSX consumen el mismo servicio (`territorial_analysis.py`) y deben dar los mismos resultados. El cumplimiento se calcula con totales, no promediando porcentajes; sin resultado definitivo se muestra `N/D`. Solo cuentan los expedientes enviados, en seguimiento o cerrados.
- **Flujo del expediente**: borrador → pendiente de aprobación directiva → enviado → en respuesta → en revisión → requiere corrección → cierre solicitado → cerrado. El detalle de reglas de negocio está en `docs/architecture.md`.

## Producción

Ver `docs/production-security.md`, `docs/release-verification.md` y `docs/daily-operations.md`. Despliegue en Linux con Gunicorn, Nginx, systemd y ClamAV mediante `deploy/install-production.sh --domain <dominio> --cert <fullchain> --key <llave>` (el certificado lo entrega el Ministerio). El instalador respalda PostgreSQL con `deploy/backup-database.sh` antes de migrar y reinicia el servicio al final; es idempotente y se reutiliza para actualizaciones. El servicio no arranca si `manage.py deployment_preflight` no devuelve cinco `[OK]` (BD, migraciones, almacenamiento privado, antivirus y SMTP). El temporizador `siga-mineducyt-overdue.timer` ejecuta `process_overdue_recommendations` a diario. `siga-mineducyt-backup.timer` respalda cada día PostgreSQL y `private/` con restic (`deploy/backup.sh`, solo si existen `backup.env` y `restic-password`), y `siga-mineducyt-verify-storage.timer` ejecuta cada semana `verify_private_storage --checksums` (existencia, tamaño y SHA-256 de cada archivo registrado).
