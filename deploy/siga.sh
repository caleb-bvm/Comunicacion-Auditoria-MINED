#!/usr/bin/env bash
# Comando de administración `siga`: ejecuta manage.py con el usuario y la
# configuración del servicio. instalar-servidor.sh lo instala en /usr/local/bin/siga.
#   siga deployment_preflight
#   siga import_center_emails /srv/carga-inicial/Listado.xlsx --dry-run
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    exec sudo "$0" "$@"
fi

# --pty permite comandos interactivos (shell, createsuperuser); sin terminal se usa --pipe.
if [[ -t 0 && -t 1 ]]; then
    mode=--pty
else
    mode=--pipe
fi
exec systemd-run --quiet --wait --collect "$mode" \
    --uid=siga-mineducyt --gid=siga-mineducyt \
    --property=WorkingDirectory=/srv/siga-mineducyt \
    --property=EnvironmentFile=/etc/siga-mineducyt/production.env \
    --setenv=DJANGO_SETTINGS_MODULE=config.settings.production \
    /srv/siga-mineducyt/.venv/bin/python manage.py "$@"
