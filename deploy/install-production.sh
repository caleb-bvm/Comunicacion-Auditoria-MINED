#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/srv/siga-mineducyt"
ENV_FILE="/etc/siga-mineducyt/production.env"
SERVICE_USER="siga-mineducyt"
SERVICE_GROUP="siga-mineducyt"
PRIVATE_DIR="/var/lib/siga-mineducyt/private"
BACKUP_DIR="/var/lib/siga-mineducyt/backups"
NGINX_CONFIG="/etc/nginx/conf.d/siga-mineducyt.conf"
DOMAIN=""
CERT_FILE=""
KEY_FILE=""

usage() {
    cat <<'EOF'
Uso:
  sudo bash ./deploy/install-production.sh --domain auditoria.example.org \
      [--cert /ruta/fullchain.pem --key /ruta/privkey.pem]

Sin --cert ni --key se usa /etc/letsencrypt/live/<dominio>/{fullchain,privkey}.pem.
Para un certificado institucional, --cert debe contener el certificado del servidor
seguido de la cadena intermedia.

Requisitos:
  - Código instalado en /srv/siga-mineducyt y entorno virtual ya creado.
  - /etc/siga-mineducyt/production.env completo.
  - PostgreSQL (con pg_dump), ClamAV, Nginx y el certificado TLS ya configurados.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --domain)
            [[ $# -ge 2 ]] || fail "Falta el valor de --domain."
            DOMAIN="$2"
            shift 2
            ;;
        --cert)
            [[ $# -ge 2 ]] || fail "Falta el valor de --cert."
            CERT_FILE="$2"
            shift 2
            ;;
        --key)
            [[ $# -ge 2 ]] || fail "Falta el valor de --key."
            KEY_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Opción desconocida: $1"
            ;;
    esac
done

[[ ${EUID} -eq 0 ]] || fail "Ejecute este archivo con sudo."
[[ "$DOMAIN" =~ ^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$ ]] || \
    fail "Indique un dominio válido mediante --domain."

for command in date getent id install mktemp nginx pg_dump sed systemctl systemd-run; do
    command -v "$command" >/dev/null || fail "No se encontró el comando requerido: $command"
done

[[ -f "$ENV_FILE" ]] || fail "No existe $ENV_FILE."
[[ -f "$APP_DIR/manage.py" ]] || fail "No existe $APP_DIR/manage.py."
[[ -x "$APP_DIR/.venv/bin/python" ]] || fail "No existe el Python del entorno virtual."
[[ -f "$APP_DIR/deploy/siga-mineducyt.service" ]] || fail "Faltan las plantillas de systemd."
[[ -f "$APP_DIR/deploy/nginx.conf" ]] || fail "Falta la plantilla de Nginx."
id "$SERVICE_USER" >/dev/null 2>&1 || fail "No existe el usuario $SERVICE_USER."
getent group "$SERVICE_GROUP" >/dev/null 2>&1 || fail "No existe el grupo $SERVICE_GROUP."

if [[ -n "$CERT_FILE" || -n "$KEY_FILE" ]]; then
    [[ -n "$CERT_FILE" && -n "$KEY_FILE" ]] || fail "Indique --cert y --key juntos."
else
    CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    KEY_FILE="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
fi
for path in "$CERT_FILE" "$KEY_FILE"; do
    [[ "$path" =~ ^/[A-Za-z0-9._/-]+$ ]] || \
        fail "La ruta $path debe ser absoluta y contener solo letras, números, '.', '_', '-' y '/'."
    [[ -f "$path" ]] || fail "No se encontró el archivo de certificado $path."
done

echo "[1/9] Protegiendo configuración y preparando directorios..."
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$PRIVATE_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$BACKUP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0755 "$APP_DIR/staticfiles"

run_django() {
    local unit="$1"
    shift
    systemd-run --quiet --wait --pipe --collect \
        --unit="$unit" \
        --uid="$SERVICE_USER" \
        --gid="$SERVICE_GROUP" \
        --property="WorkingDirectory=$APP_DIR" \
        --property="EnvironmentFile=$ENV_FILE" \
        --setenv=DJANGO_SETTINGS_MODULE=config.settings.production \
        "$APP_DIR/.venv/bin/python" manage.py "$@"
}

echo "[2/9] Respaldando la base de datos antes de migrar..."
backup_file="$BACKUP_DIR/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ).dump"
systemd-run --quiet --wait --pipe --collect \
    --unit=siga-mineducyt-deploy-backup \
    --uid="$SERVICE_USER" \
    --gid="$SERVICE_GROUP" \
    --property="EnvironmentFile=$ENV_FILE" \
    /bin/bash "$APP_DIR/deploy/backup-database.sh" "$backup_file" || \
    fail "No se pudo respaldar la base de datos; no se aplicó ningún cambio."

echo "[3/9] Aplicando migraciones..."
run_django siga-mineducyt-deploy-migrate migrate --noinput

echo "[4/9] Recopilando archivos estáticos..."
run_django siga-mineducyt-deploy-static collectstatic --noinput

echo "[5/9] Ejecutando comprobaciones de seguridad..."
run_django siga-mineducyt-deploy-check check --deploy

echo "[6/9] Comprobando dependencias externas..."
run_django siga-mineducyt-deploy-preflight deployment_preflight

echo "[7/9] Instalando unidades systemd..."
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt.service" /etc/systemd/system/siga-mineducyt.service
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt-overdue.service" /etc/systemd/system/siga-mineducyt-overdue.service
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt-overdue.timer" /etc/systemd/system/siga-mineducyt-overdue.timer
systemctl daemon-reload

echo "[8/9] Instalando y validando Nginx..."
nginx_tmp="$(mktemp)"
trap 'rm -f "$nginx_tmp"' EXIT
sed -e "s/auditoria\.example\.org/$DOMAIN/g" \
    -e "s|__SSL_CERTIFICATE__|$CERT_FILE|g" \
    -e "s|__SSL_CERTIFICATE_KEY__|$KEY_FILE|g" \
    "$APP_DIR/deploy/nginx.conf" >"$nginx_tmp"
install -o root -g root -m 0644 "$nginx_tmp" "$NGINX_CONFIG"
nginx -t

echo "[9/9] Habilitando servicios y comprobando la tarea diaria..."
systemctl enable siga-mineducyt.service
# restart (no enable --now) para que una actualización cargue el código nuevo.
systemctl restart siga-mineducyt.service
systemctl enable --now siga-mineducyt-overdue.timer
systemctl start siga-mineducyt-overdue.service
systemctl reload nginx

systemctl --no-pager --full status siga-mineducyt.service
systemctl --no-pager --full status siga-mineducyt-overdue.timer
systemctl --no-pager --full status siga-mineducyt-overdue.service

echo
echo "Despliegue completado: https://$DOMAIN"
echo "Copia previa de la base de datos: $backup_file"
echo "Revise los registros con: journalctl -u siga-mineducyt.service -u siga-mineducyt-overdue.service --since today"
