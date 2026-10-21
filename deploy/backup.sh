#!/usr/bin/env bash
# Respaldo diario, cifrado e incremental de PostgreSQL y de los archivos privados con restic.
# Lo ejecuta siga-mineducyt-backup.service con production.env y backup.env cargados.
# Primero se copia la base de datos y después los archivos: como los archivos no se
# borran, cada copia contiene todos los archivos a los que apunta su base de datos.
set -Eeuo pipefail

APP_DIR="/srv/siga-mineducyt"
BACKUP_DIR="/var/lib/siga-mineducyt/backups"
STAGING_DIR="$BACKUP_DIR/daily"
PRIVATE_DIR="${PRIVATE_MEDIA_ROOT:-/var/lib/siga-mineducyt/private}"
# Nombre fijo para que la retención no dependa del nombre del servidor.
SNAPSHOT_HOST="siga-mineducyt"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

command -v restic >/dev/null || fail "No se encontró restic."
[[ -n "${RESTIC_REPOSITORY:-}" ]] || fail "Falta RESTIC_REPOSITORY en backup.env."
# systemd entrega la clave mediante LoadCredential=restic-password.
if [[ -z "${RESTIC_PASSWORD_FILE:-}" && -n "${CREDENTIALS_DIRECTORY:-}" ]]; then
    export RESTIC_PASSWORD_FILE="$CREDENTIALS_DIRECTORY/restic-password"
fi
[[ -r "${RESTIC_PASSWORD_FILE:-}" ]] || fail "No se puede leer la clave del repositorio restic."
[[ -d "$PRIVATE_DIR" ]] || fail "No existe el almacenamiento privado $PRIVATE_DIR."

umask 077
install -d -m 0700 "$STAGING_DIR"

restic cat config >/dev/null || \
    fail "El repositorio $RESTIC_REPOSITORY no es accesible o no fue inicializado con 'restic init'."

echo "[1/4] Copiando la base de datos..."
bash "$APP_DIR/deploy/backup-database.sh" "$STAGING_DIR/siga-mineducyt.dump"

echo "[2/4] Enviando base de datos y archivos privados al repositorio..."
restic backup --host "$SNAPSHOT_HOST" --tag siga-mineducyt \
    --exclude '.preflight-*' \
    "$STAGING_DIR/siga-mineducyt.dump" "$PRIVATE_DIR"

echo "[3/4] Aplicando la retención..."
if [[ "${BACKUP_PRUNE:-true}" == "true" ]]; then
    restic forget --host "$SNAPSHOT_HOST" --tag siga-mineducyt --prune \
        --keep-daily "${BACKUP_KEEP_DAILY:-14}" \
        --keep-weekly "${BACKUP_KEEP_WEEKLY:-8}" \
        --keep-monthly "${BACKUP_KEEP_MONTHLY:-24}"
else
    echo "Retención delegada al servidor del repositorio (BACKUP_PRUNE=false)."
fi
# Las copias previas a cada despliegue ya quedan en el repositorio externo.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pre-deploy-*.dump' \
    -mtime +"${BACKUP_PREDEPLOY_DAYS:-30}" -delete

echo "[4/4] Comprobando el repositorio..."
# Lee cada día una muestra distinta de los datos guardados, no solo su índice.
restic check --read-data-subset="${BACKUP_CHECK_SUBSET:-2%}"

echo "Respaldo completado."
