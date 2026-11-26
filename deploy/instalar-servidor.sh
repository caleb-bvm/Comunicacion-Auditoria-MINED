#!/usr/bin/env bash
# Instalador interactivo de SIGA-MINEDUCYT para Ubuntu 24.04 o Debian 13 (o posteriores).
#
# Prepara todo lo que exige deploy/install-production.sh (paquetes, usuario del
# servicio, PostgreSQL, ClamAV, certificado, production.env y respaldo), pregunta en
# la terminal los datos que faltan, ejecuta ese instalador y crea la primera cuenta
# de administración técnica. Puede ejecutarse de nuevo para publicar una
# actualización: reutiliza la configuración guardada y solo pregunta lo que falte.
#
# Uso, desde la copia del repositorio (por ejemplo /srv/siga-mineducyt):
#   sudo bash deploy/instalar-servidor.sh [--reconfigurar]
#
# ask, ask_secret, load_env y save_env reciben el nombre de la variable (local -n):
# shellcheck disable=SC2034,SC2154,SC2178
set -Eeuo pipefail
umask 022

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_DIR="/srv/siga-mineducyt"
CONFIG_DIR="/etc/siga-mineducyt"
ENV_FILE="$CONFIG_DIR/production.env"
STATE_FILE="$CONFIG_DIR/instalador.env"
BACKUP_ENV_FILE="$CONFIG_DIR/backup.env"
BACKUP_PASSWORD_FILE="$CONFIG_DIR/restic-password"
TLS_DIR="$CONFIG_DIR/tls"
TEST_CA_CERT="$TLS_DIR/SIGA-MINEDUCYT-CA.crt"
TEST_CA_KEY="$TLS_DIR/SIGA-MINEDUCYT-CA.key"
# Copia pública de la autoridad de pruebas, para descargarla con scp sin ser root.
TEST_CA_PUBLIC="/usr/local/share/siga-mineducyt/SIGA-MINEDUCYT-CA.crt"
POSTGRES_CA_FILE="$CONFIG_DIR/postgres-ca.crt"
SERVICE_USER="siga-mineducyt"
STATE_DIR="/var/lib/siga-mineducyt"
CLAMD_CONF="/etc/clamav/clamd.conf"
FRESHCLAM_CONF="/etc/clamav/freshclam.conf"
LOG_FILE="/var/log/siga-mineducyt-instalacion.log"
DOMAIN_PATTERN='^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$'
RECONFIGURE=false
TOTAL_STEPS=9
ORIGINAL_ARGS="$*"

usage() {
    cat <<'EOF'
Uso:
  sudo bash deploy/instalar-servidor.sh [--reconfigurar]

Instala o actualiza SIGA-MINEDUCYT en Ubuntu 24.04 o Debian 13 (o posteriores).
La primera vez pregunta el dominio, el certificado, el correo, la base de datos,
el respaldo y la cuenta de administración. Las siguientes reutiliza lo guardado
en /etc/siga-mineducyt y solo actualiza el código y los servicios.

  --reconfigurar   Vuelve a preguntar todos los datos (conserva los actuales
                   como valores sugeridos).
EOF
}

while (($#)); do
    case "$1" in
        --reconfigurar) RECONFIGURE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Opción desconocida: $1" >&2; usage >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------------------
# Mensajes y preguntas
# ---------------------------------------------------------------------------

if [[ -t 1 ]]; then
    C_STEP=$'\e[1;36m' C_OK=$'\e[32m' C_WARN=$'\e[33m' C_ERR=$'\e[1;31m' C_DIM=$'\e[2m' C_END=$'\e[0m'
else
    C_STEP="" C_OK="" C_WARN="" C_ERR="" C_DIM="" C_END=""
fi
current_step=0

step() {
    current_step=$((current_step + 1))
    printf '\n%s[%d/%d] %s%s\n' "$C_STEP" "$current_step" "$TOTAL_STEPS" "$1" "$C_END"
}
ok() { printf '  %s✓%s %s\n' "$C_OK" "$C_END" "$*"; }
info() { printf '  %s\n' "$*"; }
hint() { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_END"; }
warn() { printf '  %s! %s%s\n' "$C_WARN" "$*" "$C_END" >&2; }
fail() {
    printf '\n%sERROR: %s%s\n' "$C_ERR" "$*" "$C_END" >&2
    exit 1
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

# ask VARIABLE "Pregunta" [predeterminado] [vacio]
ask() {
    local -n _target="$1"
    local label="$2" default="${3:-}" allow_empty="${4:-}" answer
    while true; do
        if [[ -n "$default" ]]; then
            printf '  %s [%s]: ' "$label" "$default" >&2
        else
            printf '  %s: ' "$label" >&2
        fi
        IFS= read -r answer || fail "Se cerró la entrada antes de terminar."
        answer="$(trim "$answer")"
        [[ -z "$answer" ]] && answer="$default"
        if [[ -n "$answer" || "$allow_empty" == vacio ]]; then
            _target="$answer"
            return 0
        fi
        warn "Este dato es obligatorio."
    done
}

# ask_secret VARIABLE "Pregunta" [confirmar] [vacio]
ask_secret() {
    local -n _secret="$1"
    local label="$2" confirm="${3:-}" allow_empty="${4:-}" first second
    while true; do
        printf '  %s: ' "$label" >&2
        IFS= read -rs first || fail "Se cerró la entrada antes de terminar."
        printf '\n' >&2
        if [[ -z "$first" && "$allow_empty" != vacio ]]; then
            warn "Este dato es obligatorio."
            continue
        fi
        if [[ "$confirm" == confirmar ]]; then
            printf '  Repita %s: ' "${label,}" >&2
            IFS= read -rs second || fail "Se cerró la entrada antes de terminar."
            printf '\n' >&2
            if [[ "$first" != "$second" ]]; then
                warn "No coinciden; escríbala de nuevo."
                continue
            fi
        fi
        _secret="$first"
        return 0
    done
}

# ask_yes_no "Pregunta" s|n  -> 0 si la respuesta es sí
ask_yes_no() {
    local label="$1" default="${2:-s}" answer options
    [[ "$default" == s ]] && options="S/n" || options="s/N"
    while true; do
        printf '  %s [%s]: ' "$label" "$options" >&2
        IFS= read -r answer || fail "Se cerró la entrada antes de terminar."
        answer="$(trim "${answer,,}")"
        [[ -z "$answer" ]] && answer="$default"
        case "$answer" in
            s|si|sí|y|yes) return 0 ;;
            n|no) return 1 ;;
        esac
        warn "Responda s o n."
    done
}

# Carpetas temporales que se borran al terminar (también si hay un error).
CLEANUP_DIRS=()
new_workdir() {
    local -n _dir="$1"
    _dir="$(mktemp -d)"
    CLEANUP_DIRS+=("$_dir")
}
cleanup() {
    ((${#CLEANUP_DIRS[@]})) && rm -rf "${CLEANUP_DIRS[@]}"
    return 0
}
trap cleanup EXIT

random_secret() {
    python3 -c 'import secrets, string, sys
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(int(sys.argv[1]))))' "$1"
}

# ---------------------------------------------------------------------------
# Archivos KEY=VALUE con el formato de EnvironmentFile de systemd
# ---------------------------------------------------------------------------

declare -A CONF=() STATE=()
CONF_KEYS=()
STATE_KEYS=()

env_unquote() {
    local value="$1" out="" char next i
    if [[ ${#value} -ge 2 && "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
        for ((i = 0; i < ${#value}; i++)); do
            char="${value:i:1}"
            if [[ "$char" == '\' ]] && ((i + 1 < ${#value})); then
                next="${value:i+1:1}"
                case "$next" in
                    '"'|'\'|'$'|'`') char="$next"; i=$((i + 1)) ;;
                esac
            fi
            out+="$char"
        done
        value="$out"
    elif [[ ${#value} -ge 2 && "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
    fi
    printf '%s' "$value"
}

env_quote() {
    local value="$1"
    if [[ "$value" =~ ^[A-Za-z0-9._@:/,+=-]*$ ]]; then
        printf '%s' "$value"
        return
    fi
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//\$/\\\$}"
    value="${value//\`/\\\`}"
    printf '"%s"' "$value"
}

# load_env ARCHIVO ARREGLO LISTA_DE_CLAVES
load_env() {
    local file="$1" line key
    local -n _values="$2" _keys="$3"
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        [[ -v "_values[$key]" ]] || _keys+=("$key")
        _values["$key"]="$(env_unquote "$(trim "${BASH_REMATCH[2]}")")"
    done <"$file"
}

# set_value ARREGLO LISTA_DE_CLAVES CLAVE VALOR
set_value() {
    local -n _values="$1" _keys="$2"
    [[ -v "_values[$3]" ]] || _keys+=("$3")
    _values["$3"]="$4"
}
conf() { set_value CONF CONF_KEYS "$1" "$2"; }
state() { set_value STATE STATE_KEYS "$1" "$2"; }

# save_env ARCHIVO ARREGLO LISTA_DE_CLAVES "comentario"
save_env() {
    local file="$1" key tmp
    local -n _values="$2" _keys="$3"
    tmp="$(mktemp "$CONFIG_DIR/.env.XXXXXX")"
    {
        printf '# %s\n' "$4"
        printf '# Generado por deploy/instalar-servidor.sh. Puede editarse; se conserva al actualizar.\n'
        for key in "${_keys[@]}"; do
            printf '%s=%s\n' "$key" "$(env_quote "${_values[$key]}")"
        done
    } >"$tmp"
    chown root:root "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$file"
}

# ---------------------------------------------------------------------------
# Utilidades del sistema
# ---------------------------------------------------------------------------

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "$@" </dev/null
}

# Ejecuta el Python del proyecto como el usuario del servicio, con production.env.
# Las opciones --setenv=... deben ir primero.
service_python() {
    local -a options=()
    while (($#)) && [[ "$1" == --setenv=* ]]; do
        options+=("$1")
        shift
    done
    systemd-run --quiet --wait --pipe --collect \
        --uid="$SERVICE_USER" --gid="$SERVICE_USER" \
        --property=WorkingDirectory="$APP_DIR" \
        --property=EnvironmentFile="$ENV_FILE" \
        --setenv=DJANGO_SETTINGS_MODULE=config.settings.production \
        --setenv=PYTHONDONTWRITEBYTECODE=1 \
        --setenv=PYTHONUTF8=1 \
        "${options[@]}" \
        "$APP_DIR/.venv/bin/python" "$@"
}

clamav_ping() {
    (
        response=""
        exec 3<>/dev/tcp/127.0.0.1/3310 || exit 1
        printf 'zPING\0' >&3
        IFS= read -r -d '' -t 5 response <&3 || true
        [[ "$response" == PONG ]]
    ) 2>/dev/null
}

pg_admin() {
    (cd / && runuser -u postgres -- psql -X "$@")
}

# set_config_line ARCHIVO CLAVE VALOR (formato «Clave valor» de ClamAV)
set_config_line() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^[#[:space:]]*${key}([[:space:]]|$)" "$file"; then
        sed -i -E "0,/^[#[:space:]]*${key}([[:space:]]|\$).*/s//${key} ${value//\//\\/}/" "$file"
        # Quita repeticiones posteriores de la misma clave.
        awk -v key="$key" 'BEGIN { seen = 0 }
            $1 == key { if (seen) next; seen = 1 }
            { print }' "$file" >"$file.tmp" && cat "$file.tmp" >"$file" && rm -f "$file.tmp"
    else
        printf '%s %s\n' "$key" "$value" >>"$file"
    fi
}

cert_pubkey_hash() { openssl x509 -in "$1" -noout -pubkey 2>/dev/null | openssl sha256 | awk '{print $NF}'; }
key_pubkey_hash() { openssl pkey -in "$1" -pubout 2>/dev/null | openssl sha256 | awk '{print $NF}'; }

cert_covers_domain() {
    openssl x509 -in "$1" -noout -checkhost "$2" 2>/dev/null | grep -q "does match"
}

# ---------------------------------------------------------------------------
# Registro y errores
# ---------------------------------------------------------------------------

[[ ${EUID} -eq 0 ]] || { echo "Ejecute el instalador con sudo: sudo bash deploy/instalar-servidor.sh" >&2; exit 1; }

( umask 077; touch "$LOG_FILE" )
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1
printf '\n===== %s  instalar-servidor.sh %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$ORIGINAL_ARGS" >>"$LOG_FILE"

on_error() {
    local code=$? line=$1
    printf '\n%sLa instalación se detuvo (línea %s, código %s).%s\n' "$C_ERR" "$line" "$code" "$C_END" >&2
    printf 'Revise los mensajes anteriores y el registro %s.\n' "$LOG_FILE" >&2
    printf 'Corrija el problema y ejecute de nuevo: sudo bash %s/deploy/instalar-servidor.sh\n' "$SOURCE_DIR" >&2
}
trap 'on_error $LINENO' ERR

printf '%sSIGA-MINEDUCYT · instalación del servidor%s\n' "$C_STEP" "$C_END"
info "Código de origen: $SOURCE_DIR"
info "Registro de esta instalación: $LOG_FILE"

# ---------------------------------------------------------------------------
# 1. Sistema
# ---------------------------------------------------------------------------

step "Comprobando el sistema"
[[ -f "$SOURCE_DIR/manage.py" && -f "$SOURCE_DIR/deploy/install-production.sh" ]] || \
    fail "Ejecute el archivo desde la copia del repositorio (no se encontró manage.py junto a deploy/)."
[[ -r /etc/os-release ]] || fail "No se pudo identificar el sistema operativo."
# shellcheck disable=SC1091
. /etc/os-release
[[ " ${ID:-} ${ID_LIKE:-} " == *" debian "* || " ${ID:-} ${ID_LIKE:-} " == *" ubuntu "* ]] && command -v apt-get >/dev/null || \
    fail "Este instalador es para Ubuntu o Debian. Sistema detectado: ${PRETTY_NAME:-desconocido}."
command -v systemctl >/dev/null && [[ -d /run/systemd/system ]] || fail "Se requiere systemd en ejecución."
ok "${PRETTY_NAME:-$ID}"

memory_mb=$(awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo)
cores=$(nproc)
disk_gb=$(df -Pk /var/lib | awk 'NR == 2 { print int($4 / 1048576) }')
ok "Memoria: ${memory_mb} MB · Núcleos: ${cores} · Espacio libre en /var/lib: ${disk_gb} GB"
((memory_mb >= 3000)) || warn "ClamAV usa unos 1,5 GB de memoria; con menos de 3 GB el servidor puede quedarse corto."
((disk_gb >= 20)) || warn "Hay menos de 20 GB libres; los informes anteriores ocupan unos 7,3 GB más las copias de la base."

load_env "$ENV_FILE" CONF CONF_KEYS
load_env "$STATE_FILE" STATE STATE_KEYS
if [[ -f "$ENV_FILE" ]]; then
    ok "Configuración existente: $ENV_FILE (se reutiliza)"
fi

# ---------------------------------------------------------------------------
# 2. Programas
# ---------------------------------------------------------------------------

step "Instalando los programas"
info "Actualizando la lista de paquetes..."
DEBIAN_FRONTEND=noninteractive apt-get update -q </dev/null
packages=(python3 python3-venv nginx clamav clamav-daemon clamav-freshclam postgresql-client
    restic curl rsync openssl ca-certificates gzip)
apt_install "${packages[@]}"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || \
    fail "SIGA requiere Python 3.12 o posterior y este sistema tiene $(python3 -V 2>&1). Use Ubuntu 24.04 o Debian 13."
ok "$(python3 -V), $(nginx -v 2>&1 | sed 's|.*/||; s|^|Nginx |'), $(clamd --version | cut -d/ -f1), $(psql --version | awk '{print "psql " $3}')"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --user-group --home-dir "$STATE_DIR" --no-create-home \
        --shell /usr/sbin/nologin "$SERVICE_USER"
    ok "Usuario del servicio creado: $SERVICE_USER"
else
    ok "Usuario del servicio: $SERVICE_USER"
fi
install -d -o root -g root -m 0755 "$CONFIG_DIR"
install -d -o root -g root -m 0700 "$TLS_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$STATE_DIR/private"

# ---------------------------------------------------------------------------
# 3. Datos de la instalación
# ---------------------------------------------------------------------------

step "Datos de la instalación"

# --- Dominio ---------------------------------------------------------------
DOMAIN="${STATE[DOMAIN]:-}"
if [[ -z "$DOMAIN" || "$RECONFIGURE" == true ]]; then
    hint "El dominio es la dirección con la que se abrirá SIGA, por ejemplo auditoria.mined.gob.sv."
    suggested="${DOMAIN:-}"
    if [[ -z "$suggested" ]]; then
        suggested="$(hostname -f 2>/dev/null || true)"
        [[ "$suggested" =~ $DOMAIN_PATTERN ]] || suggested=""
    fi
    while true; do
        ask DOMAIN "Dominio del sistema" "$suggested"
        DOMAIN="${DOMAIN,,}"
        [[ "$DOMAIN" =~ $DOMAIN_PATTERN ]] && break
        warn "Escriba un nombre de dominio completo (no una dirección IP), por ejemplo auditoria.mined.gob.sv."
    done
    if [[ -n "${STATE[DOMAIN]:-}" && "${STATE[DOMAIN]}" != "$DOMAIN" ]]; then
        state TLS_MODE ""
    fi
    state DOMAIN "$DOMAIN"
fi
resolved="$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
if [[ -z "$resolved" ]]; then
    warn "$DOMAIN todavía no resuelve a ninguna dirección. Pida a TI el registro DNS (o agréguelo al archivo hosts de cada equipo para pruebas)."
else
    ok "Dominio: $DOMAIN → $resolved"
fi

# --- Certificado -----------------------------------------------------------
CERT_FILE="$TLS_DIR/fullchain.pem"
KEY_FILE="$TLS_DIR/privkey.pem"

normalize_certificate() {
    # normalize_certificate CERTIFICADOS LLAVE [CADENA] -> deja fullchain y llave en $TLS_DIR
    local cert_input="$1" key_input="$2" chain_input="${3:-}" work leaf key_hash file
    new_workdir work
    cat "$cert_input" ${chain_input:+"$chain_input"} >"$work/all.pem"
    awk -v dir="$work" '
        /-----BEGIN CERTIFICATE-----/ { n++; out = sprintf("%s/cert-%02d.pem", dir, n) }
        out { print > out }
        /-----END CERTIFICATE-----/ { close(out); out = "" }' "$work/all.pem"
    compgen -G "$work/cert-*.pem" >/dev/null || { warn "El archivo no contiene certificados."; return 1; }
    key_hash="$(key_pubkey_hash "$key_input")"
    leaf=""
    for file in "$work"/cert-*.pem; do
        if [[ "$(cert_pubkey_hash "$file")" == "$key_hash" ]]; then
            leaf="$file"
            break
        fi
    done
    [[ -n "$leaf" ]] || { warn "La llave privada no corresponde a ningún certificado del archivo."; return 1; }
    if ! cert_covers_domain "$leaf" "$DOMAIN"; then
        warn "El certificado no incluye $DOMAIN. Nombres del certificado:"
        openssl x509 -in "$leaf" -noout -ext subjectAltName 2>/dev/null | sed 's/^/    /' >&2 || true
        return 1
    fi
    if ! openssl x509 -in "$leaf" -noout -checkend 0 >/dev/null; then
        warn "El certificado ya venció ($(openssl x509 -in "$leaf" -noout -enddate | cut -d= -f2))."
        return 1
    fi
    openssl x509 -in "$leaf" -noout -checkend 2592000 >/dev/null || \
        warn "El certificado vence en menos de 30 días."
    # El certificado del servidor primero y después la cadena, como espera Nginx.
    {
        openssl x509 -in "$leaf"
        for file in "$work"/cert-*.pem; do
            [[ "$file" == "$leaf" ]] || openssl x509 -in "$file"
        done
    } >"$work/fullchain.pem"
    local -a untrusted=()
    [[ $(compgen -G "$work/cert-*.pem" | wc -l) -gt 1 ]] && untrusted=(-untrusted "$work/fullchain.pem")
    if ! openssl verify "${untrusted[@]}" "$leaf" >/dev/null 2>&1; then
        warn "No se pudo validar la cadena del certificado con las autoridades del sistema."
        warn "Si los navegadores muestran advertencias, pida al Ministerio la cadena intermedia."
    fi
    install -o root -g root -m 0644 "$work/fullchain.pem" "$CERT_FILE"
    install -o root -g root -m 0600 "$key_input" "$KEY_FILE"
    ok "Certificado instalado, válido hasta $(openssl x509 -in "$CERT_FILE" -noout -enddate | cut -d= -f2)"
}

import_ministry_certificate() {
    local cert_path key_path chain_path="" pfx_password key_password work
    new_workdir work
    hint "Copie antes al servidor los archivos del Ministerio (por ejemplo con scp a /root/)."
    hint "Se acepta .pem/.crt/.cer con su llave .key, o un archivo .pfx/.p12 que contenga ambos."
    while true; do
        ask cert_path "Ruta del certificado (.pem, .crt, .cer, .pfx o .p12)"
        [[ -f "$cert_path" ]] || { warn "No existe $cert_path."; continue; }
        if [[ "${cert_path,,}" == *.pfx || "${cert_path,,}" == *.p12 ]]; then
            ask_secret pfx_password "Contraseña del archivo .pfx (vacía si no tiene)" "" vacio
            local -a legacy=()
            if ! PFX_PASSWORD="$pfx_password" openssl pkcs12 -in "$cert_path" -passin env:PFX_PASSWORD \
                    -nokeys -out "$work/cert.pem" 2>/dev/null; then
                legacy=(-legacy)
                PFX_PASSWORD="$pfx_password" openssl pkcs12 "${legacy[@]}" -in "$cert_path" \
                    -passin env:PFX_PASSWORD -nokeys -out "$work/cert.pem" 2>/dev/null || {
                    warn "No se pudo abrir el .pfx: revise la contraseña."
                    continue
                }
            fi
            PFX_PASSWORD="$pfx_password" openssl pkcs12 "${legacy[@]}" -in "$cert_path" \
                -passin env:PFX_PASSWORD -nocerts -nodes -out "$work/key-raw.pem" 2>/dev/null || {
                warn "El .pfx no contiene la llave privada."
                continue
            }
            openssl pkey -in "$work/key-raw.pem" -out "$work/key.pem" 2>/dev/null || {
                warn "No se pudo leer la llave del .pfx."
                continue
            }
        else
            if grep -q -- "-----BEGIN CERTIFICATE-----" "$cert_path"; then
                cp "$cert_path" "$work/cert.pem"
            elif ! openssl x509 -inform DER -in "$cert_path" -out "$work/cert.pem" 2>/dev/null; then
                warn "$cert_path no es un certificado reconocible."
                continue
            fi
            ask key_path "Ruta de la llave privada (.key o .pem)"
            [[ -f "$key_path" ]] || { warn "No existe $key_path."; continue; }
            if ! openssl pkey -in "$key_path" -passin pass: -out "$work/key.pem" 2>/dev/null; then
                ask_secret key_password "La llave tiene contraseña; escríbala"
                KEY_PASSWORD="$key_password" openssl pkey -in "$key_path" -passin env:KEY_PASSWORD \
                    -out "$work/key.pem" 2>/dev/null || { warn "No se pudo abrir la llave."; continue; }
            fi
            if [[ $(grep -c -- "-----BEGIN CERTIFICATE-----" "$work/cert.pem") -eq 1 ]] && \
                    [[ "$(openssl x509 -in "$work/cert.pem" -noout -issuer | cut -d= -f2-)" != \
                       "$(openssl x509 -in "$work/cert.pem" -noout -subject | cut -d= -f2-)" ]]; then
                hint "El archivo solo trae el certificado del servidor; los navegadores también necesitan la cadena intermedia."
                ask chain_path "Ruta de la cadena intermedia (vacío si no la tiene)" "" vacio
                if [[ -n "$chain_path" && ! -f "$chain_path" ]]; then
                    warn "No existe $chain_path."
                    continue
                fi
            fi
        fi
        chmod 600 "$work/key.pem"
        if normalize_certificate "$work/cert.pem" "$work/key.pem" "$chain_path"; then
            return 0
        fi
        warn "Revise los archivos e inténtelo de nuevo."
    done
}

create_test_certificate() {
    local work
    if [[ -f "$CERT_FILE" && -f "$KEY_FILE" && -f "$TEST_CA_CERT" ]] \
            && cert_covers_domain "$CERT_FILE" "$DOMAIN" \
            && openssl x509 -in "$CERT_FILE" -noout -checkend 2592000 >/dev/null \
            && openssl verify -CAfile "$TEST_CA_CERT" "$CERT_FILE" >/dev/null 2>&1; then
        ok "Certificado de pruebas vigente para $DOMAIN"
        return 0
    fi
    new_workdir work
    if [[ ! -f "$TEST_CA_CERT" || ! -f "$TEST_CA_KEY" ]]; then
        openssl req -x509 -newkey rsa:3072 -nodes -sha256 -days 3650 \
            -keyout "$TEST_CA_KEY" -out "$TEST_CA_CERT" \
            -subj "/O=SIGA-MINEDUCYT/CN=SIGA-MINEDUCYT CA de pruebas" \
            -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
            -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
        chmod 600 "$TEST_CA_KEY"
        chmod 644 "$TEST_CA_CERT"
        ok "Autoridad de pruebas creada: $TEST_CA_CERT"
    fi
    cat >"$work/ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:$DOMAIN
EOF
    openssl req -new -newkey rsa:2048 -nodes -sha256 -keyout "$work/key.pem" -out "$work/req.csr" \
        -subj "/O=SIGA-MINEDUCYT/CN=$DOMAIN" 2>/dev/null
    openssl x509 -req -sha256 -days 730 -in "$work/req.csr" -CA "$TEST_CA_CERT" -CAkey "$TEST_CA_KEY" \
        -set_serial "0x$(openssl rand -hex 16)" -extfile "$work/ext.cnf" -out "$work/cert.pem" 2>/dev/null
    cat "$work/cert.pem" "$TEST_CA_CERT" >"$work/fullchain.pem"
    install -o root -g root -m 0644 "$work/fullchain.pem" "$CERT_FILE"
    install -o root -g root -m 0600 "$work/key.pem" "$KEY_FILE"
    ok "Certificado de pruebas para $DOMAIN, válido por 2 años"
}

TLS_MODE="${STATE[TLS_MODE]:-}"
LE_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
existing_cert="$CERT_FILE"
[[ "$TLS_MODE" == letsencrypt ]] && existing_cert="$LE_CERT"
tls_ready=false
if [[ -n "$TLS_MODE" && -f "$existing_cert" ]] && cert_covers_domain "$existing_cert" "$DOMAIN" \
        && openssl x509 -in "$existing_cert" -noout -checkend 0 >/dev/null; then
    tls_ready=true
fi
if [[ "$tls_ready" == true && "$RECONFIGURE" == false ]]; then
    if [[ "$TLS_MODE" == temporal ]]; then
        create_test_certificate
    else
        ok "Certificado ($TLS_MODE), válido hasta $(openssl x509 -in "$existing_cert" -noout -enddate | cut -d= -f2)"
    fi
else
    [[ -n "$TLS_MODE" && "$tls_ready" == false && "$RECONFIGURE" == false ]] && \
        warn "El certificado guardado ya no sirve para $DOMAIN (falta, venció o no incluye el dominio)."
    info "Certificado HTTPS:"
    info "  1) Certificado entregado por el Ministerio"
    info "  2) Certificado temporal de pruebas (los equipos deben instalar la autoridad de pruebas)"
    le_available=false
    if [[ -f "$LE_CERT" ]]; then
        le_available=true
        info "  3) Certificado de Let's Encrypt ya emitido para $DOMAIN"
    fi
    while true; do
        ask choice "Opción" "1"
        case "$choice" in
            1) import_ministry_certificate; TLS_MODE=ministerio; break ;;
            2) create_test_certificate; TLS_MODE=temporal; break ;;
            3) [[ "$le_available" == true ]] && { TLS_MODE=letsencrypt; break; } ;;
        esac
        warn "Elija una de las opciones."
    done
    state TLS_MODE "$TLS_MODE"
fi
if [[ "$TLS_MODE" == letsencrypt ]]; then
    CERT_FILE="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    KEY_FILE="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
fi

# --- Correo ----------------------------------------------------------------
if [[ -z "${CONF[EMAIL_HOST]:-}" || "$RECONFIGURE" == true ]]; then
    info ""
    info "Correo para invitaciones y avisos (SMTP)."
    hint "Con Google Workspace o Gmail: smtp.gmail.com, puerto 587 y una contraseña de aplicación"
    hint "(myaccount.google.com/apppasswords). El servidor debe poder salir a ese puerto."
    while true; do
        ask smtp_host "Servidor SMTP" "${CONF[EMAIL_HOST]:-smtp.gmail.com}"
        ask smtp_port "Puerto (587 STARTTLS, 465 SSL)" "${CONF[EMAIL_PORT]:-587}"
        ask smtp_user "Usuario (correo completo)" "${CONF[EMAIL_HOST_USER]:-}" vacio
        smtp_password=""
        if [[ -n "$smtp_user" ]]; then
            if [[ -n "${CONF[EMAIL_HOST_PASSWORD]:-}" ]]; then
                ask_secret smtp_password "Contraseña (vacía para conservar la actual)" "" vacio
                [[ -z "$smtp_password" ]] && smtp_password="${CONF[EMAIL_HOST_PASSWORD]}"
            else
                ask_secret smtp_password "Contraseña del correo"
            fi
        fi
        ask smtp_from "Remitente que verán los usuarios" "${CONF[DEFAULT_FROM_EMAIL]:-$smtp_user}"
        smtp_ssl=false
        [[ "$smtp_port" == 465 ]] && smtp_ssl=true
        info "Probando la conexión..."
        if EMAIL_HOST="$smtp_host" EMAIL_PORT="$smtp_port" EMAIL_HOST_USER="$smtp_user" \
                EMAIL_HOST_PASSWORD="$smtp_password" EMAIL_USE_SSL="$smtp_ssl" \
                python3 "$SOURCE_DIR/deploy/probar_smtp.py" </dev/null | sed 's/^/  /'; then
            break
        fi
        ask_yes_no "¿Volver a escribir los datos del correo?" s || \
            fail "Sin un correo que funcione SIGA no puede iniciar (deployment_preflight lo comprueba)."
    done
    conf EMAIL_HOST "$smtp_host"
    conf EMAIL_PORT "$smtp_port"
    conf EMAIL_HOST_USER "$smtp_user"
    conf EMAIL_HOST_PASSWORD "$smtp_password"
    if [[ "$smtp_ssl" == true ]]; then
        conf EMAIL_USE_TLS false
        conf EMAIL_USE_SSL true
    else
        conf EMAIL_USE_TLS true
        conf EMAIL_USE_SSL false
    fi
    conf DEFAULT_FROM_EMAIL "$smtp_from"
    ok "Correo configurado: $smtp_host ($smtp_from)"
else
    ok "Correo: ${CONF[EMAIL_HOST]} (${CONF[DEFAULT_FROM_EMAIL]:-})"
fi

# --- Base de datos ---------------------------------------------------------
DB_MODE="${STATE[DB_MODE]:-}"
if [[ -z "$DB_MODE" && -n "${CONF[POSTGRES_HOST]:-}" ]]; then
    case "${CONF[POSTGRES_HOST]}" in
        127.0.0.1|::1|localhost) DB_MODE=local ;;
        *) DB_MODE=remota ;;
    esac
fi
if [[ -z "$DB_MODE" || "$RECONFIGURE" == true ]]; then
    info ""
    info "Base de datos PostgreSQL."
    if ask_yes_no "¿Instalar PostgreSQL en este mismo servidor? (n = usar un servidor de TI)" \
            "$([[ "$DB_MODE" == remota ]] && echo n || echo s)"; then
        DB_MODE=local
    else
        DB_MODE=remota
        hint "La conexión a otro servidor va cifrada y verificada (sslmode=verify-full):"
        hint "se necesita el certificado de la autoridad que firmó el del servidor PostgreSQL."
        while true; do
            ask db_host "Servidor PostgreSQL (nombre del certificado)" \
                "$([[ "${CONF[POSTGRES_HOST]:-}" != 127.0.0.1 ]] && echo "${CONF[POSTGRES_HOST]:-}")"
            ask db_port "Puerto" "${CONF[POSTGRES_PORT]:-5432}"
            ask db_name "Base de datos" "${CONF[POSTGRES_DB]:-siga_mineducyt}"
            ask db_user "Usuario" "${CONF[POSTGRES_USER]:-siga_mineducyt_app}"
            ask_secret db_password "Contraseña del usuario"
            ask db_ca "Ruta del certificado de la autoridad (.crt/.pem)" \
                "$([[ -f "$POSTGRES_CA_FILE" ]] && echo "$POSTGRES_CA_FILE")"
            [[ -f "$db_ca" ]] || { warn "No existe $db_ca."; continue; }
            info "Probando la conexión..."
            if version="$(PGPASSWORD="$db_password" PGSSLMODE=verify-full PGSSLROOTCERT="$db_ca" \
                    PGCONNECT_TIMEOUT=10 psql -X -h "$db_host" -p "$db_port" -U "$db_user" -d "$db_name" \
                    -tAc 'SHOW server_version_num' 2>&1)"; then
                break
            fi
            warn "No se pudo conectar: $version"
            ask_yes_no "¿Volver a escribir los datos de la base?" s || fail "Sin base de datos no se puede continuar."
        done
        [[ "$db_ca" -ef "$POSTGRES_CA_FILE" ]] || install -o root -g root -m 0644 "$db_ca" "$POSTGRES_CA_FILE"
        server_major=$((version / 10000))
        client_major="$(pg_dump --version | awk '{ split($3, v, "."); print v[1] }')"
        if ((server_major > client_major)); then
            warn "El servidor usa PostgreSQL $server_major y este equipo tiene pg_dump $client_major: los respaldos fallarán."
            warn "Instale postgresql-client-$server_major desde apt.postgresql.org y ejecute de nuevo el instalador."
        fi
        conf POSTGRES_HOST "$db_host"
        conf POSTGRES_PORT "$db_port"
        conf POSTGRES_DB "$db_name"
        conf POSTGRES_USER "$db_user"
        conf POSTGRES_PASSWORD "$db_password"
        conf POSTGRES_SSLMODE verify-full
        conf POSTGRES_SSLROOTCERT "$POSTGRES_CA_FILE"
        ok "Base de datos remota: $db_user@$db_host:$db_port/$db_name"
    fi
    state DB_MODE "$DB_MODE"
fi

# --- Respaldo --------------------------------------------------------------
if [[ ( ! -f "$BACKUP_ENV_FILE" || ! -f "$BACKUP_PASSWORD_FILE" ) \
        && ( "${STATE[BACKUP_ASKED]:-}" != si || "$RECONFIGURE" == true ) ]]; then
    info ""
    info "Respaldo diario cifrado (restic) de la base de datos y los documentos."
    hint "Debe ir a un repositorio fuera de este servidor: rest-server de TI o almacenamiento S3."
    if ask_yes_no "¿Configurarlo ahora?" s; then
        while true; do
            hint "Ejemplos: rest:https://usuario:clave@respaldos.mined.gob.sv:8000/siga-mineducyt"
            hint "          s3:https://almacenamiento.example/siga-mineducyt"
            ask restic_repo "Repositorio"
            restic_extra=()
            if [[ "$restic_repo" == s3:* ]]; then
                ask s3_key "AWS_ACCESS_KEY_ID"
                ask_secret s3_secret "AWS_SECRET_ACCESS_KEY"
                restic_extra=("AWS_ACCESS_KEY_ID=$s3_key" "AWS_SECRET_ACCESS_KEY=$s3_secret")
            fi
            work_password="$(mktemp)"
            if [[ -f "$BACKUP_PASSWORD_FILE" ]]; then
                cp "$BACKUP_PASSWORD_FILE" "$work_password"
            else
                openssl rand -base64 48 >"$work_password"
            fi
            chmod 600 "$work_password"
            info "Comprobando el repositorio..."
            if env "${restic_extra[@]}" RESTIC_REPOSITORY="$restic_repo" RESTIC_PASSWORD_FILE="$work_password" \
                    restic cat config </dev/null >/dev/null 2>&1; then
                ok "El repositorio ya existe y la clave es correcta"
            elif env "${restic_extra[@]}" RESTIC_REPOSITORY="$restic_repo" RESTIC_PASSWORD_FILE="$work_password" \
                    restic init </dev/null 2>&1 | sed 's/^/  /'; then
                ok "Repositorio inicializado"
            else
                rm -f "$work_password"
                warn "No se pudo usar el repositorio. Si ya existe, copie su clave en $BACKUP_PASSWORD_FILE."
                if ask_yes_no "¿Escribir otro repositorio?" s; then
                    continue
                fi
                warn "Se continúa sin respaldo. No cargue datos reales hasta configurarlo."
                break
            fi
            install -o root -g root -m 0600 "$work_password" "$BACKUP_PASSWORD_FILE"
            rm -f "$work_password"
            declare -A BACKUP=()
            BACKUP_KEYS=()
            load_env "$SOURCE_DIR/deploy/backup.env.example" BACKUP BACKUP_KEYS
            set_value BACKUP BACKUP_KEYS RESTIC_REPOSITORY "$restic_repo"
            if [[ "$restic_repo" == s3:* ]]; then
                set_value BACKUP BACKUP_KEYS AWS_ACCESS_KEY_ID "$s3_key"
                set_value BACKUP BACKUP_KEYS AWS_SECRET_ACCESS_KEY "$s3_secret"
            fi
            save_env "$BACKUP_ENV_FILE" BACKUP BACKUP_KEYS "Respaldo de SIGA-MINEDUCYT (ver deploy/backup.env.example)"
            if [[ "$restic_repo" == /* ]]; then
                # Un disco local montado: el respaldo corre como el usuario del servicio y
                # necesita ser dueño del repositorio (restic init lo creó como root) y
                # permiso de escritura en esa ruta.
                chown -R "$SERVICE_USER:$SERVICE_USER" "$restic_repo"
                install -d -m 0755 /etc/systemd/system/siga-mineducyt-backup.service.d
                printf '[Service]\nReadWritePaths=%s\n' "$restic_repo" \
                    >/etc/systemd/system/siga-mineducyt-backup.service.d/repositorio.conf
                warn "Un disco de este mismo servidor no protege ante la pérdida del equipo."
            fi
            ok "Respaldo configurado: $BACKUP_ENV_FILE"
            warn "Guarde una copia de $BACKUP_PASSWORD_FILE fuera del servidor: sin ella no se puede restaurar."
            break
        done
    else
        warn "Sin respaldo. Antes de cargar datos reales, ejecute: sudo bash deploy/instalar-servidor.sh --reconfigurar"
    fi
    state BACKUP_ASKED si
elif [[ -f "$BACKUP_ENV_FILE" && -f "$BACKUP_PASSWORD_FILE" ]]; then
    ok "Respaldo: $BACKUP_ENV_FILE"
else
    warn "El respaldo sigue sin configurar (--reconfigurar para hacerlo)."
fi

save_env "$STATE_FILE" STATE STATE_KEYS "Respuestas del instalador de SIGA-MINEDUCYT"

# ---------------------------------------------------------------------------
# 4. PostgreSQL
# ---------------------------------------------------------------------------

step "Preparando PostgreSQL"
if [[ "$DB_MODE" == local ]]; then
    apt_install postgresql
    systemctl enable --now --quiet postgresql
    for _ in $(seq 1 30); do
        pg_admin -tAc 'SELECT 1' >/dev/null 2>&1 && break
        sleep 1
    done
    pg_admin -tAc 'SELECT 1' >/dev/null || fail "PostgreSQL no respondió."
    conf POSTGRES_HOST 127.0.0.1
    conf POSTGRES_PORT "${CONF[POSTGRES_PORT]:-5432}"
    [[ -n "${CONF[POSTGRES_DB]:-}" ]] || conf POSTGRES_DB siga_mineducyt
    [[ -n "${CONF[POSTGRES_USER]:-}" ]] || conf POSTGRES_USER siga_mineducyt_app
    [[ -n "${CONF[POSTGRES_PASSWORD]:-}" ]] || conf POSTGRES_PASSWORD "$(random_secret 40)"
    conf POSTGRES_SSLMODE disable
    conf POSTGRES_SSLROOTCERT ""
    db_name="${CONF[POSTGRES_DB]}"
    db_user="${CONF[POSTGRES_USER]}"
    sql_password="${CONF[POSTGRES_PASSWORD]//\'/\'\'}"
    # La contraseña va por la entrada estándar, no en la línea de comandos.
    pg_admin -q -v ON_ERROR_STOP=1 -v app_user="$db_user" -v app_db="$db_name" <<SQL
SELECT format('CREATE ROLE %I LOGIN', :'app_user')
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
              :'app_user', '$sql_password') \gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING %L TEMPLATE template0', :'app_db', :'app_user', 'UTF8')
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'app_db') \gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'app_db', :'app_user') \gexec
SQL
    PGPASSWORD="${CONF[POSTGRES_PASSWORD]}" psql -X -h 127.0.0.1 -p "${CONF[POSTGRES_PORT]}" \
        -U "$db_user" -d "$db_name" -tAc 'SELECT 1' >/dev/null || \
        fail "La aplicación no pudo conectarse a PostgreSQL con su usuario."
    ok "PostgreSQL $(pg_admin -tAc 'SHOW server_version' | cut -d' ' -f1): base $db_name, usuario $db_user"
else
    PGPASSWORD="${CONF[POSTGRES_PASSWORD]}" PGSSLMODE="${CONF[POSTGRES_SSLMODE]:-verify-full}" \
        PGSSLROOTCERT="${CONF[POSTGRES_SSLROOTCERT]:-}" PGCONNECT_TIMEOUT=10 \
        psql -X -h "${CONF[POSTGRES_HOST]}" -p "${CONF[POSTGRES_PORT]:-5432}" \
        -U "${CONF[POSTGRES_USER]}" -d "${CONF[POSTGRES_DB]}" -tAc 'SELECT 1' >/dev/null || \
        fail "No se pudo conectar a ${CONF[POSTGRES_HOST]}. Revise la red o ejecute con --reconfigurar."
    ok "Base de datos remota disponible: ${CONF[POSTGRES_HOST]}"
fi

# ---------------------------------------------------------------------------
# 5. ClamAV
# ---------------------------------------------------------------------------

step "Configurando el antivirus ClamAV"
max_upload_mb="${CONF[FILE_MAX_UPLOAD_MB]:-20}"
stream_mb=$((max_upload_mb * 2 > 40 ? max_upload_mb * 2 : 40))
[[ -f "$CLAMD_CONF.siga-original" ]] || cp -p "$CLAMD_CONF" "$CLAMD_CONF.siga-original"
set_config_line "$CLAMD_CONF" TCPSocket 3310
set_config_line "$CLAMD_CONF" TCPAddr 127.0.0.1
set_config_line "$CLAMD_CONF" StreamMaxLength "${stream_mb}M"
set_config_line "$CLAMD_CONF" MaxFileSize "${stream_mb}M"
set_config_line "$CLAMD_CONF" MaxScanSize "$((stream_mb * 4))M"
set_config_line "$CLAMD_CONF" AlertExceedsMax yes
set_config_line "$CLAMD_CONF" AlertEncrypted yes
if ((memory_mb < 4000)); then
    # Recargar las firmas en paralelo duplica la memoria durante unos segundos.
    set_config_line "$CLAMD_CONF" ConcurrentDatabaseReload no
fi
proxy="${https_proxy:-${HTTPS_PROXY:-${http_proxy:-${HTTP_PROXY:-}}}}"
if [[ "$proxy" =~ ^[a-z]+://([^/:@]+@)?([^/:]+):([0-9]+) ]]; then
    set_config_line "$FRESHCLAM_CONF" HTTPProxyServer "${BASH_REMATCH[2]}"
    set_config_line "$FRESHCLAM_CONF" HTTPProxyPort "${BASH_REMATCH[3]}"
    ok "freshclam usará el proxy ${BASH_REMATCH[2]}:${BASH_REMATCH[3]}"
fi
ok "clamd escucha en 127.0.0.1:3310 (archivos de hasta ${stream_mb} MB)"

info "Descargando las firmas del antivirus (la primera vez tarda unos minutos)..."
systemctl stop clamav-freshclam.service 2>/dev/null || true
freshclam --stdout </dev/null 2>&1 | sed 's/^/  /' || warn "freshclam terminó con errores; se comprueba si ya hay firmas."
if ! compgen -G "/var/lib/clamav/main.c[lv]d" >/dev/null || ! compgen -G "/var/lib/clamav/daily.c[lv]d" >/dev/null; then
    fail "No se pudieron descargar las firmas de ClamAV. Compruebe la salida a Internet (o el proxy) y ejecute de nuevo."
fi
systemctl enable --now --quiet clamav-freshclam.service
systemctl enable --quiet clamav-daemon.service
systemctl restart clamav-daemon.service
info "Esperando a que ClamAV cargue las firmas..."
clamav_ready=false
for _ in $(seq 1 90); do
    if clamav_ping; then
        clamav_ready=true
        break
    fi
    sleep 2
done
if [[ "$clamav_ready" != true ]]; then
    journalctl -u clamav-daemon.service -n 30 --no-pager >&2 || true
    fail "ClamAV no respondió en 127.0.0.1:3310 después de 3 minutos."
fi
ok "ClamAV responde"

# ---------------------------------------------------------------------------
# 6. Código
# ---------------------------------------------------------------------------

step "Instalando el código en $APP_DIR"
if [[ "$SOURCE_DIR" -ef "$APP_DIR" ]]; then
    ok "Se usa la copia que ya está en $APP_DIR"
else
    install -d -o root -g root -m 0755 "$APP_DIR"
    # Las carpetas excluidas (.venv, staticfiles) se conservan en el destino.
    rsync -a --delete --chown=root:root --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
        --exclude=/.git/ --exclude=/.venv/ --exclude=/staticfiles/ --exclude=/media/ \
        --include=/.env.example --exclude='/.env*' \
        --exclude=/.claude/ --exclude=/.vscode/ --exclude=/.idea/ \
        --exclude='__pycache__/' --exclude='*.pyc' \
        "$SOURCE_DIR/" "$APP_DIR/"
    if git -C "$SOURCE_DIR" rev-parse --short HEAD >/dev/null 2>&1; then
        ok "Código copiado desde $SOURCE_DIR (revisión $(git -C "$SOURCE_DIR" rev-parse --short HEAD))"
    else
        ok "Código copiado desde $SOURCE_DIR"
    fi
fi
# El servicio solo lee el código: legible por todos y modificable solo por root.
find "$APP_DIR" -path "$APP_DIR/.venv" -prune -o -path "$APP_DIR/staticfiles" -prune \
    -o ! -name '.env*' -exec chmod a+rX,go-w {} +
runuser -u "$SERVICE_USER" -- test -r "$APP_DIR/manage.py" || \
    fail "El usuario $SERVICE_USER no puede leer $APP_DIR. Revise los permisos de las carpetas superiores."

system_python="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
venv_python="$("$APP_DIR/.venv/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
if [[ "$venv_python" != "$system_python" ]]; then
    [[ -d "$APP_DIR/.venv" ]] && rm -rf "$APP_DIR/.venv"
    python3 -m venv "$APP_DIR/.venv"
    ok "Entorno de Python $system_python creado"
else
    ok "Entorno de Python $venv_python"
fi
install -o root -g root -m 0755 "$APP_DIR/deploy/siga.sh" /usr/local/bin/siga
ok "Comando de administración instalado: siga <comando de manage.py>"

# ---------------------------------------------------------------------------
# 7. Configuración
# ---------------------------------------------------------------------------

step "Escribiendo la configuración"
[[ -n "${CONF[DJANGO_SECRET_KEY]:-}" ]] || conf DJANGO_SECRET_KEY "$(random_secret 64)"
conf DJANGO_ALLOWED_HOSTS "$DOMAIN"
conf DJANGO_CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
conf PUBLIC_BASE_URL "https://$DOMAIN"
if [[ "$TLS_MODE" == temporal ]]; then
    # Con el certificado de pruebas, HSTS dejaría bloqueados los equipos sin la autoridad.
    conf DJANGO_HSTS_SECONDS 0
elif [[ -z "${CONF[DJANGO_HSTS_SECONDS]:-}" || "${CONF[DJANGO_HSTS_SECONDS]}" == 0 ]]; then
    conf DJANGO_HSTS_SECONDS 3600
fi
conf FILE_SCAN_REQUIRED true
[[ -n "${CONF[FILE_MAX_UPLOAD_MB]:-}" ]] || conf FILE_MAX_UPLOAD_MB 20
[[ -n "${CONF[PRIVATE_MEDIA_ROOT]:-}" ]] || conf PRIVATE_MEDIA_ROOT "$STATE_DIR/private"
conf CLAMAV_HOST 127.0.0.1
conf CLAMAV_PORT 3310
if [[ -z "${CONF[WEB_CONCURRENCY]:-}" ]]; then
    # 2 x núcleos + 1, limitado por la memoria que deja ClamAV (~150 MB por proceso).
    workers=$((cores * 2 + 1))
    by_memory=$(((memory_mb - 2000) / 150))
    ((by_memory < workers)) && workers=$by_memory
    ((workers > 9)) && workers=9
    ((workers < 2)) && workers=2
    conf WEB_CONCURRENCY "$workers"
fi
save_env "$ENV_FILE" CONF CONF_KEYS "Configuración de producción de SIGA-MINEDUCYT (ver .env.example)"
ok "$ENV_FILE (solo root)"

if command -v ufw >/dev/null && LC_ALL=C ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ok "Firewall (ufw): puertos 80 y 443 abiertos"
else
    info "No hay un firewall ufw activo en este equipo. Si TI administra otro firewall, pida abrir 80 y 443."
fi
hint "8000 (Gunicorn), 5432 (PostgreSQL) y 3310 (ClamAV) solo escuchan dentro del servidor."

# ---------------------------------------------------------------------------
# 8. Servicio
# ---------------------------------------------------------------------------

step "Instalando y arrancando el servicio"
hint "Valida Nginx y Django, respalda la base, migra, prepara los estáticos y comprueba"
hint "base de datos, migraciones, almacenamiento, antivirus y correo antes de arrancar."
# install-production.sh recarga Nginx al final: debe estar en marcha.
systemctl enable --now --quiet nginx.service
bash "$APP_DIR/deploy/install-production.sh" --domain "$DOMAIN" --cert "$CERT_FILE" --key "$KEY_FILE" </dev/null

# ---------------------------------------------------------------------------
# 9. Cuenta de administración
# ---------------------------------------------------------------------------

step "Cuenta de administración técnica"
admin_created=""
if service_python deploy/crear_admin.py existe </dev/null; then
    ok "Ya existe una cuenta de administración técnica"
else
    info "Cree la cuenta de administración técnica (desde ella se crean las demás)."
    while true; do
        ask admin_user "Usuario"
        ask admin_first "Nombres" "" vacio
        ask admin_last "Apellidos" "" vacio
        ask admin_email "Correo" "" vacio
        ask_secret admin_password "Contraseña" confirmar
        if printf '%s\n' "$admin_password" | service_python \
                --setenv=SIGA_ADMIN_USERNAME="$admin_user" \
                --setenv=SIGA_ADMIN_FIRST_NAME="$admin_first" \
                --setenv=SIGA_ADMIN_LAST_NAME="$admin_last" \
                --setenv=SIGA_ADMIN_EMAIL="$admin_email" \
                deploy/crear_admin.py crear | sed 's/^/  /'; then
            admin_created="$admin_user"
            break
        fi
        warn "Corrija los datos indicados e inténtelo de nuevo."
    done
fi
unset admin_password smtp_password db_password

# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

printf '\n%sSIGA-MINEDUCYT quedó instalado.%s\n\n' "$C_OK" "$C_END"
info "Dirección:        https://$DOMAIN"
[[ -n "$admin_created" ]] && info "Administración:   $admin_created (desde /tecnica/usuarios/nuevo/ se crean Dirección y auditores)"
info "Configuración:    $ENV_FILE"
info "Documentos:       ${CONF[PRIVATE_MEDIA_ROOT]}"
info "Registros:        journalctl -u siga-mineducyt.service --since today"
info "Administrar:      siga deployment_preflight · siga import_center_emails ARCHIVO --dry-run"
info "Actualizar:       cd $SOURCE_DIR && sudo git pull --ff-only && sudo bash deploy/instalar-servidor.sh"
if [[ "$TLS_MODE" == temporal ]]; then
    echo
    install -D -o root -g root -m 0644 "$TEST_CA_CERT" "$TEST_CA_PUBLIC"
    warn "Certificado de pruebas: cada equipo debe instalar $TEST_CA_PUBLIC"
    warn "como autoridad de confianza (cópielo con: scp usuario@servidor:$TEST_CA_PUBLIC .)"
    warn "y resolver $DOMAIN hacia este servidor (DNS o archivo hosts)."
fi
if [[ ! -f "$BACKUP_ENV_FILE" ]]; then
    echo
    warn "El respaldo diario está desactivado. No cargue datos reales sin configurarlo."
fi
info ""
info "Siga con la carga del catálogo y los informes: docs/initial-deployment.md, pasos 13 a 17."
