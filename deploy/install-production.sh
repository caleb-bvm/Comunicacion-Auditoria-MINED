#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/srv/siga-mineducyt"
ENV_FILE="/etc/siga-mineducyt/production.env"
BACKUP_ENV_FILE="/etc/siga-mineducyt/backup.env"
BACKUP_PASSWORD_FILE="/etc/siga-mineducyt/restic-password"
SERVICE_USER="siga-mineducyt"
SERVICE_GROUP="siga-mineducyt"
STATE_DIR="/var/lib/siga-mineducyt"
PRIVATE_DIR="$STATE_DIR/private"
BACKUP_DIR="$STATE_DIR/backups"
# Huellas del último despliegue correcto: dependencias y todo lo que obliga a reiniciar.
# Fuera de /var/lib/siga-mineducyt, que systemd entrega al usuario del servicio.
DEPLOY_STATE="/etc/siga-mineducyt/deploy-state"
NGINX_CONFIG="/etc/nginx/conf.d/siga-mineducyt.conf"
SERVICE_UNIT="/etc/systemd/system/siga-mineducyt.service"
DOMAIN=""
CERT_FILE=""
KEY_FILE=""
FORCE_RESTART=false

usage() {
    cat <<'EOF'
Uso:
  sudo bash ./deploy/install-production.sh --domain auditoria.example.org \
      [--cert /ruta/fullchain.pem --key /ruta/privkey.pem] [--restart]

Sin --cert ni --key se usa /etc/letsencrypt/live/<dominio>/{fullchain,privkey}.pem.
Para un certificado institucional, --cert debe contener el certificado del servidor
seguido de la cadena intermedia.

Si el servicio ya funciona y no cambiaron production.env, requirements.txt ni la
unidad de systemd, se recarga Gunicorn sin cortar las solicitudes en curso.
--restart obliga a un reinicio completo.

Requisitos:
  - Código instalado en /srv/siga-mineducyt y entorno virtual ya creado.
  - /etc/siga-mineducyt/production.env completo.
  - PostgreSQL (con pg_dump), ClamAV, Nginx y el certificado TLS ya configurados.

Respaldo automático (recomendado): restic instalado, repositorio inicializado,
/etc/siga-mineducyt/backup.env y /etc/siga-mineducyt/restic-password. Sin ellos
el instalador continúa, pero deja el respaldo diario desactivado.
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
        --restart)
            FORCE_RESTART=true
            shift
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

for command in cmp curl cut date getent gzip id install journalctl mktemp nginx pg_dump sed seq \
        sha256sum systemctl systemd-run; do
    command -v "$command" >/dev/null || fail "No se encontró el comando requerido: $command"
done

[[ -f "$ENV_FILE" ]] || fail "No existe $ENV_FILE."
[[ -f "$APP_DIR/manage.py" ]] || fail "No existe $APP_DIR/manage.py."
[[ -f "$APP_DIR/requirements.txt" ]] || fail "No existe $APP_DIR/requirements.txt."
[[ -x "$APP_DIR/.venv/bin/python" ]] || fail "No existe el Python del entorno virtual."
[[ -f "$APP_DIR/deploy/siga-mineducyt.service" ]] || fail "Faltan las plantillas de systemd."
[[ -f "$APP_DIR/deploy/nginx.conf" ]] || fail "Falta la plantilla de Nginx."
[[ -f "$APP_DIR/deploy/compress-static.sh" ]] || fail "Falta deploy/compress-static.sh."
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

BACKUP_CONFIGURED=false
if [[ -f "$BACKUP_ENV_FILE" || -f "$BACKUP_PASSWORD_FILE" ]]; then
    [[ -f "$BACKUP_ENV_FILE" && -f "$BACKUP_PASSWORD_FILE" ]] || \
        fail "Para el respaldo se requieren $BACKUP_ENV_FILE y $BACKUP_PASSWORD_FILE."
    command -v restic >/dev/null || fail "No se encontró restic, requerido por el respaldo automático."
    BACKUP_CONFIGURED=true
fi

cleanup_files=()
cleanup() {
    ((${#cleanup_files[@]})) && rm -f "${cleanup_files[@]}"
    return 0
}
trap cleanup EXIT

state_value() {
    [[ -f "$DEPLOY_STATE" ]] || return 0
    sed -n "s/^$1=//p" "$DEPLOY_STATE"
}

# El intérprete forma parte de la huella: un Python nuevo exige reinstalar paquetes.
deps_hash="$({ cat "$APP_DIR/requirements.txt"; "$APP_DIR/.venv/bin/python" -VV; } | sha256sum | cut -d' ' -f1)"
restart_hash="$(cat "$ENV_FILE" "$APP_DIR/deploy/siga-mineducyt.service" "$APP_DIR/requirements.txt" \
    | sha256sum | cut -d' ' -f1)"

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

echo "[1/10] Protegiendo configuración y preparando directorios..."
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"
if [[ "$BACKUP_CONFIGURED" == true ]]; then
    chown root:root "$BACKUP_ENV_FILE" "$BACKUP_PASSWORD_FILE"
    chmod 600 "$BACKUP_ENV_FILE" "$BACKUP_PASSWORD_FILE"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$PRIVATE_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$BACKUP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0755 "$APP_DIR/staticfiles"

# Nginx y la configuración de Django se validan antes de tocar la base de datos:
# un certificado o una variable incorrecta detienen el despliegue sin cambios.
echo "[2/10] Validando Nginx..."
nginx_tmp="$(mktemp)"
nginx_previous="$(mktemp)"
cleanup_files+=("$nginx_tmp" "$nginx_previous")
sed -e "s/auditoria\.example\.org/$DOMAIN/g" \
    -e "s|__SSL_CERTIFICATE__|$CERT_FILE|g" \
    -e "s|__SSL_CERTIFICATE_KEY__|$KEY_FILE|g" \
    "$APP_DIR/deploy/nginx.conf" >"$nginx_tmp"
had_nginx_config=false
if [[ -f "$NGINX_CONFIG" ]]; then
    cp -p "$NGINX_CONFIG" "$nginx_previous"
    had_nginx_config=true
fi
install -o root -g root -m 0644 "$nginx_tmp" "$NGINX_CONFIG"
# El sitio de ejemplo de Debian/Ubuntu también declara default_server en el
# puerto 80 y haría fallar nginx -t. Solo se quita el enlace; el archivo original
# sigue en sites-available.
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    rm /etc/nginx/sites-enabled/default
    echo "Se desactivó el sitio predeterminado de Nginx (sites-enabled/default)."
elif [[ -e /etc/nginx/sites-enabled/default ]]; then
    fail "/etc/nginx/sites-enabled/default no es un enlace; revíselo y quítelo manualmente."
fi
if ! nginx -t; then
    if [[ "$had_nginx_config" == true ]]; then
        install -o root -g root -m 0644 "$nginx_previous" "$NGINX_CONFIG"
    else
        rm -f "$NGINX_CONFIG"
    fi
    fail "La configuración de Nginx no es válida; se restauró la anterior y no se aplicó ningún cambio."
fi

echo "[3/10] Actualizando dependencias de Python..."
if [[ "$(state_value deps)" == "$deps_hash" ]]; then
    echo "requirements.txt no cambió desde el último despliegue; se omite pip."
else
    "$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --no-input --quiet \
        -r "$APP_DIR/requirements.txt" || fail "No se pudieron instalar las dependencias."
fi
# El código es de root y el servicio no puede escribir __pycache__: sin esto, cada
# proceso de Gunicorn recompila los módulos al iniciar y al reciclarse.
"$APP_DIR/.venv/bin/python" -m compileall -q -j 0 "$APP_DIR/apps" "$APP_DIR/config" || \
    fail "No se pudo compilar el código de la aplicación."

echo "[4/10] Ejecutando comprobaciones de seguridad..."
run_django siga-mineducyt-deploy-check check --deploy

echo "[5/10] Respaldando la base de datos antes de migrar..."
backup_file="$BACKUP_DIR/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ).dump"
systemd-run --quiet --wait --pipe --collect \
    --unit=siga-mineducyt-deploy-backup \
    --uid="$SERVICE_USER" \
    --gid="$SERVICE_GROUP" \
    --property="EnvironmentFile=$ENV_FILE" \
    /bin/bash "$APP_DIR/deploy/backup-database.sh" "$backup_file" || \
    fail "No se pudo respaldar la base de datos; no se aplicó ningún cambio."

echo "[6/10] Aplicando migraciones..."
run_django siga-mineducyt-deploy-migrate migrate --noinput

echo "[7/10] Recopilando y comprimiendo archivos estáticos..."
run_django siga-mineducyt-deploy-static collectstatic --noinput
# Nginx sirve las versiones .gz con gzip_static, sin comprimir en cada solicitud.
# gzip conserva la fecha del original: solo se regeneran los archivos modificados.
systemd-run --quiet --wait --pipe --collect \
    --unit=siga-mineducyt-deploy-gzip \
    --uid="$SERVICE_USER" \
    --gid="$SERVICE_GROUP" \
    /bin/bash "$APP_DIR/deploy/compress-static.sh" "$APP_DIR/staticfiles" || \
    fail "No se pudieron comprimir los archivos estáticos."

echo "[8/10] Comprobando dependencias externas..."
run_django siga-mineducyt-deploy-preflight deployment_preflight

echo "[9/10] Instalando unidades systemd..."
unit_changed=false
cmp -s "$APP_DIR/deploy/siga-mineducyt.service" "$SERVICE_UNIT" || unit_changed=true
for unit in siga-mineducyt.service siga-mineducyt-overdue.service siga-mineducyt-overdue.timer \
        siga-mineducyt-backup.service siga-mineducyt-backup.timer \
        siga-mineducyt-verify-storage.service siga-mineducyt-verify-storage.timer; do
    install -o root -g root -m 0644 "$APP_DIR/deploy/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload

echo "[10/10] Activando la nueva versión..."
systemctl enable --quiet siga-mineducyt.service
if [[ "$FORCE_RESTART" == false && "$unit_changed" == false ]] \
        && systemctl is-active --quiet siga-mineducyt.service \
        && [[ "$(state_value restart)" == "$restart_hash" ]]; then
    # HUP: Gunicorn levanta procesos con el código nuevo y termina los anteriores
    # cuando completan sus solicitudes. Las comprobaciones ya se ejecutaron arriba.
    echo "Recargando Gunicorn sin interrumpir el servicio..."
    systemctl reload siga-mineducyt.service
else
    echo "Reiniciando el servicio (primera instalación o cambio de configuración)..."
    systemctl restart siga-mineducyt.service
fi

echo "Esperando a que la aplicación responda..."
healthy=false
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null --max-time 5 \
            -H "Host: $DOMAIN" -H "X-Forwarded-Proto: https" \
            http://127.0.0.1:8000/ingresar/; then
        healthy=true
        break
    fi
    sleep 1
done
if [[ "$healthy" != true ]]; then
    journalctl -u siga-mineducyt.service -n 40 --no-pager >&2 || true
    fail "La aplicación no respondió en 30 segundos. Copia previa de la base de datos: $backup_file"
fi

systemctl enable --now --quiet siga-mineducyt-overdue.timer
systemctl start siga-mineducyt-overdue.service
systemctl enable --now --quiet siga-mineducyt-verify-storage.timer
if [[ "$BACKUP_CONFIGURED" == true ]]; then
    systemctl enable --now --quiet siga-mineducyt-backup.timer
else
    systemctl disable --now --quiet siga-mineducyt-backup.timer 2>/dev/null || true
fi
systemctl reload nginx

# Solo se registra al terminar bien: un despliegue fallido repite pip y reinicia.
(umask 077; printf 'deps=%s\nrestart=%s\n' "$deps_hash" "$restart_hash" >"$DEPLOY_STATE.tmp")
mv "$DEPLOY_STATE.tmp" "$DEPLOY_STATE"

systemctl --no-pager --full status siga-mineducyt.service
systemctl --no-pager --full status siga-mineducyt-overdue.service
systemctl --no-pager list-timers 'siga-mineducyt-*'

echo
echo "Despliegue completado: https://$DOMAIN"
echo "Copia previa de la base de datos: $backup_file"
if [[ "$BACKUP_CONFIGURED" != true ]]; then
    echo "ADVERTENCIA: el respaldo automático no está configurado. No cargue datos reales sin él." >&2
    echo "Consulte docs/production-security.md, sección «Respaldo y verificación de archivos»." >&2
fi
echo "Revise los registros con: journalctl -u siga-mineducyt.service -u siga-mineducyt-overdue.service --since today"
