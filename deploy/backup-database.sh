#!/usr/bin/env bash
# Genera una copia de PostgreSQL con las credenciales de production.env.
# Uso: backup-database.sh RUTA_DEL_ARCHIVO
# Debe ejecutarse con las variables POSTGRES_* cargadas (por ejemplo, mediante
# systemd-run --property=EnvironmentFile=/etc/siga-mineducyt/production.env).
set -Eeuo pipefail

[[ $# -eq 1 ]] || { echo "Uso: $0 RUTA_DEL_ARCHIVO" >&2; exit 2; }
destination="$1"

for name in POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST; do
    [[ -n "${!name:-}" ]] || { echo "ERROR: falta $name en el entorno." >&2; exit 1; }
done

export PGPASSWORD="$POSTGRES_PASSWORD"
export PGSSLMODE="${POSTGRES_SSLMODE:-verify-full}"
if [[ -n "${POSTGRES_SSLROOTCERT:-}" ]]; then
    export PGSSLROOTCERT="$POSTGRES_SSLROOTCERT"
fi

umask 077
partial="$destination.partial"
trap 'rm -f "$partial"' ERR
pg_dump --format=custom --no-owner \
    --host="$POSTGRES_HOST" --port="${POSTGRES_PORT:-5432}" \
    --username="$POSTGRES_USER" --file="$partial" "$POSTGRES_DB"
mv "$partial" "$destination"
echo "Copia creada: $destination"
