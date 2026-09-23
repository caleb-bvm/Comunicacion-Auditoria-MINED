#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/srv/siga-mineducyt"
ENV_FILE="/etc/siga-mineducyt/production.env"
SERVICE_USER="siga-mineducyt"
SERVICE_GROUP="siga-mineducyt"
PRIVATE_DIR="/var/lib/siga-mineducyt/private"
NGINX_CONFIG="/etc/nginx/conf.d/siga-mineducyt.conf"
DOMAIN=""

usage() {
    cat <<'EOF'
Uso:
  sudo bash ./deploy/install-production.sh --domain auditoria.example.org

Requisitos:
  - Código instalado en /srv/siga-mineducyt y entorno virtual ya creado.
  - /etc/siga-mineducyt/production.env completo.
  - PostgreSQL, ClamAV, Nginx y el certificado TLS ya configurados.
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

for command in getent id install mktemp nginx sed systemctl systemd-run; do
    command -v "$command" >/dev/null || fail "No se encontró el comando requerido: $command"
done

[[ -f "$ENV_FILE" ]] || fail "No existe $ENV_FILE."
[[ -f "$APP_DIR/manage.py" ]] || fail "No existe $APP_DIR/manage.py."
[[ -x "$APP_DIR/.venv/bin/python" ]] || fail "No existe el Python del entorno virtual."
[[ -f "$APP_DIR/deploy/siga-mineducyt.service" ]] || fail "Faltan las plantillas de systemd."
[[ -f "$APP_DIR/deploy/nginx.conf" ]] || fail "Falta la plantilla de Nginx."
id "$SERVICE_USER" >/dev/null 2>&1 || fail "No existe el usuario $SERVICE_USER."
getent group "$SERVICE_GROUP" >/dev/null 2>&1 || fail "No existe el grupo $SERVICE_GROUP."

cert_dir="/etc/letsencrypt/live/$DOMAIN"
[[ -f "$cert_dir/fullchain.pem" && -f "$cert_dir/privkey.pem" ]] || \
    fail "No se encontró un certificado TLS para $DOMAIN en $cert_dir."

echo "[1/8] Protegiendo configuración y preparando directorios..."
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$PRIVATE_DIR"
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

echo "[2/8] Aplicando migraciones..."
run_django siga-mineducyt-deploy-migrate migrate --noinput

echo "[3/8] Recopilando archivos estáticos..."
run_django siga-mineducyt-deploy-static collectstatic --noinput

echo "[4/8] Ejecutando comprobaciones de seguridad..."
run_django siga-mineducyt-deploy-check check --deploy

echo "[5/8] Comprobando dependencias externas..."
run_django siga-mineducyt-deploy-preflight deployment_preflight

echo "[6/8] Instalando unidades systemd..."
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt.service" /etc/systemd/system/siga-mineducyt.service
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt-overdue.service" /etc/systemd/system/siga-mineducyt-overdue.service
install -o root -g root -m 0644 "$APP_DIR/deploy/siga-mineducyt-overdue.timer" /etc/systemd/system/siga-mineducyt-overdue.timer
systemctl daemon-reload

echo "[7/8] Instalando y validando Nginx..."
nginx_tmp="$(mktemp)"
trap 'rm -f "$nginx_tmp"' EXIT
sed "s/auditoria\.example\.org/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" >"$nginx_tmp"
install -o root -g root -m 0644 "$nginx_tmp" "$NGINX_CONFIG"
nginx -t

echo "[8/8] Habilitando servicios y comprobando la tarea diaria..."
systemctl enable --now siga-mineducyt.service
systemctl enable --now siga-mineducyt-overdue.timer
systemctl start siga-mineducyt-overdue.service
systemctl reload nginx

systemctl --no-pager --full status siga-mineducyt.service
systemctl --no-pager --full status siga-mineducyt-overdue.timer
systemctl --no-pager --full status siga-mineducyt-overdue.service

echo
echo "Despliegue completado: https://$DOMAIN"
echo "Revise los registros con: journalctl -u siga-mineducyt.service -u siga-mineducyt-overdue.service --since today"
