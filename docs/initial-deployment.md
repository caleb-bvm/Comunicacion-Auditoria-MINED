# Despliegue inicial en producción

Esta guía describe, en orden, todo lo que hay que hacer para poner SIGA-MINEDUCYT en
el servidor por primera vez y dejarlo listo antes de que lo usen los centros. Para
actualizar una instalación que ya funciona basta con el paso 9.

Los detalles técnicos de seguridad, respaldo y restauración están en
[la guía de producción](production-security.md).

## Antes de empezar

Reúna lo siguiente antes de entrar al servidor:

| Qué | Para qué |
| --- | --- |
| Servidor Linux con soporte (Debian o Ubuntu) y acceso con `sudo` | Donde se instala el sistema |
| Dominio, por ejemplo `auditoria.mined.gob.sv`, apuntando al servidor | Dirección pública del sistema |
| Certificado y llave privada entregados por el Ministerio | Conexión HTTPS |
| Servidor de correo (SMTP): dirección, puerto, usuario y clave | Envío de invitaciones |
| Repositorio de respaldo fuera del servidor (rest-server o S3) | Copias diarias de la base y los archivos |
| `Listado_Cuentas_Correo_CE.xlsx` | Catálogo de centros con su correo |
| `CE HABILITADOS CON GEOREFERENCIA.xlsx` | Departamento, distrito y coordenadas de cada centro |
| Carpeta de informes anteriores ya revisada con la simulación | Carga inicial del archivo histórico |

Calcule el espacio en disco: los informes anteriores ocupan unos 7,3 GB y el
sistema guarda además copias previas de la base de datos. El respaldo diario
necesita un espacio parecido en el repositorio externo.

La versión que se instala debe estar en la rama `master` con el CI aprobado
(`check`, migraciones, pruebas y `pip-audit`).

## 1. Instalar los programas del servidor

```bash
sudo apt update
sudo apt install git python3 python3-venv postgresql nginx clamav-daemon clamav-freshclam restic
```

El proyecto se prueba con Python 3.12. Use esa versión o una más reciente.

## 2. Crear el usuario del servicio y sus carpetas

El sistema corre con un usuario propio, sin permiso para iniciar sesión.

```bash
sudo useradd --system --home /var/lib/siga-mineducyt --shell /usr/sbin/nologin siga-mineducyt
sudo install -d -o siga-mineducyt -g siga-mineducyt -m 0700 /var/lib/siga-mineducyt/private
sudo install -d -o root -g root -m 0755 /etc/siga-mineducyt
```

En `/var/lib/siga-mineducyt/private` quedan todos los documentos. Nadie más que el
usuario del servicio debe poder leer esa carpeta.

## 3. Crear la base de datos

```bash
sudo -u postgres createuser --pwprompt siga_mineducyt_app
sudo -u postgres createdb --owner siga_mineducyt_app siga_mineducyt
```

Anote la clave que escribió: va en el archivo de configuración del paso 6. Ese
usuario no es administrador de PostgreSQL y no puede crear otras bases. No abra el
puerto 5432 hacia Internet.

## 4. Configurar el antivirus

Edite `/etc/clamav/clamd.conf` y deje estos valores:

```text
TCPAddr 127.0.0.1
TCPSocket 3310
StreamMaxLength 20M
MaxFileSize 20M
MaxScanSize 100M
AlertExceedsMax yes
AlertEncrypted yes
```

Luego reinicie el servicio y espere a que descargue las firmas:

```bash
sudo systemctl restart clamav-freshclam clamav-daemon
sudo systemctl status clamav-daemon
```

Si más adelante sube el tamaño máximo de archivo (`FILE_MAX_UPLOAD_MB`), suba
también `StreamMaxLength` y `MaxFileSize` al mismo valor.

## 5. Copiar el código

Con la cuenta de administración del servidor (no con `siga-mineducyt`):

```bash
sudo git clone --branch master <URL-del-repositorio> /srv/siga-mineducyt
cd /srv/siga-mineducyt
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
```

El código pertenece a la cuenta de administración. El usuario del servicio solo
lo lee.

## 6. Escribir la configuración

```bash
sudo cp /srv/siga-mineducyt/.env.example /etc/siga-mineducyt/production.env
python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
sudo nano /etc/siga-mineducyt/production.env
```

Complete cada valor del archivo:

- `DJANGO_SECRET_KEY`: el texto que generó el segundo comando. No reutilice el del ejemplo.
- `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` y `PUBLIC_BASE_URL`: el dominio real.
- `POSTGRES_PASSWORD`: la clave del paso 3.
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`: los datos del correo institucional.

Deje `FILE_SCAN_REQUIRED=true` y `DJANGO_HSTS_SECONDS=3600`. El instalador deja el
archivo legible solo por `root`.

## 7. Instalar el certificado

Guarde el certificado y la llave del Ministerio, por ejemplo en `/etc/ssl/siga/`:

- `fullchain.pem`: el certificado del servidor seguido de la cadena intermedia, en un solo archivo.
- `privkey.pem`: la llave privada, legible solo por `root` (`chmod 600`).

Si la administración del sistema se hará desde la VPN, agregue esa red al bloque
`/administracion/` de `deploy/nginx.conf`. Por defecto ese acceso está cerrado desde
fuera.

## 8. Preparar el respaldo

Haga este paso antes del instalador para que active el respaldo diario. No cargue
datos reales sin respaldo.

```bash
sudo cp /srv/siga-mineducyt/deploy/backup.env.example /etc/siga-mineducyt/backup.env
sudo nano /etc/siga-mineducyt/backup.env
sudo sh -c 'openssl rand -base64 48 > /etc/siga-mineducyt/restic-password'
sudo chmod 600 /etc/siga-mineducyt/backup.env /etc/siga-mineducyt/restic-password
sudo sh -c 'set -a; . /etc/siga-mineducyt/backup.env; set +a; RESTIC_PASSWORD_FILE=/etc/siga-mineducyt/restic-password restic init'
```

En `backup.env` escriba la dirección del repositorio externo (`RESTIC_REPOSITORY`).
Guarde una copia de `restic-password` fuera del servidor, en un lugar con acceso
restringido. Sin esa clave las copias no se pueden recuperar.

## 9. Ejecutar el instalador

```bash
cd /srv/siga-mineducyt
sudo bash deploy/install-production.sh --domain auditoria.mined.gob.sv \
    --cert /etc/ssl/siga/fullchain.pem --key /etc/ssl/siga/privkey.pem
```

El instalador:

1. Respalda la base de datos antes de cambiar nada.
2. Aplica las migraciones. En la primera instalación esto también registra la
   Dirección de Auditoría Interna (`DAI-MINED`) y las 14 Direcciones Departamentales.
3. Prepara los archivos estáticos y revisa la configuración de seguridad.
4. Comprueba la base de datos, las migraciones, la carpeta privada, el antivirus y
   el correo. Si alguno falla, se detiene y dice cuál.
5. Instala Nginx y los servicios, y activa las tareas diarias: vencimientos,
   respaldo y verificación semanal de archivos.

Al terminar muestra la dirección del sistema. Si aparece la advertencia de que el
respaldo no está configurado, vuelva al paso 8 y ejecute de nuevo el instalador.

## 10. Abrir el firewall

Permita solo lo necesario:

- 443 (HTTPS) y 80 (redirección a HTTPS) desde Internet.
- SSH solo desde la VPN o las direcciones de administración, con llave y sin entrar directamente como `root`.
- Cierre 8000, 5432 y 3310 hacia fuera. Solo se usan dentro del servidor.

Compruebe que `https://<dominio>` abre la pantalla de ingreso.

## 11. Preparar el comando de administración

Las tareas siguientes usan `manage.py` con el mismo usuario y configuración del
servicio. Para no repetir el comando completo, defina esta función en la sesión:

```bash
siga() {
    sudo systemd-run --pty --collect --uid=siga-mineducyt --gid=siga-mineducyt \
        --property=WorkingDirectory=/srv/siga-mineducyt \
        --property=EnvironmentFile=/etc/siga-mineducyt/production.env \
        --setenv=DJANGO_SETTINGS_MODULE=config.settings.production \
        /srv/siga-mineducyt/.venv/bin/python manage.py "$@"
}
```

Pruebe con `siga deployment_preflight`: deben aparecer cinco líneas `[OK]`.

## 12. Crear las primeras cuentas

Cree la cuenta de administración técnica:

```bash
siga createsuperuser
siga shell -c "from apps.accounts.models import User; User.objects.filter(username='<usuario>').update(role='technical_admin')"
```

El segundo comando le asigna el rol de administración técnica; cambie `<usuario>`
por el nombre que eligió. Ingrese con esa cuenta y abra `https://<dominio>/tecnica/usuarios/nuevo/`. Desde ahí
cree las cuentas de la Dirección (`audit_manager`) y de cada auditor (`auditor`).
Cada persona debe cambiar su contraseña en el primer ingreso.

Las cuentas de los centros no se crean aquí. Se activan después, por invitación,
desde la ficha de cada centro.

## 13. Cargar el catálogo de centros

Desde su computadora, copie al servidor los dos archivos del catálogo y la carpeta
de informes anteriores (en PowerShell, cambiando las rutas por las suyas):

```powershell
ssh usuario@servidor "mkdir -p ~/carga-inicial"
scp "C:\ruta\Listado_Cuentas_Correo_CE.xlsx" "C:\ruta\CE HABILITADOS CON GEOREFERENCIA.xlsx" usuario@servidor:~/carga-inicial/
scp -r "C:\ruta\SIGA" usuario@servidor:~/carga-inicial/informes
```

En el servidor, pase la carpeta a un lugar que solo lea el servicio:

```bash
sudo mv ~/carga-inicial /srv/carga-inicial
sudo chown -R siga-mineducyt:siga-mineducyt /srv/carga-inicial
sudo chmod 700 /srv/carga-inicial
```

Cargue primero los centros y sus correos, luego la ubicación. En cada caso, revise
la simulación (`--dry-run`) antes de la carga real:

```bash
siga import_center_emails /srv/carga-inicial/Listado_Cuentas_Correo_CE.xlsx --dry-run
siga import_center_emails /srv/carga-inicial/Listado_Cuentas_Correo_CE.xlsx
siga import_center_locations "/srv/carga-inicial/CE HABILITADOS CON GEOREFERENCIA.xlsx" --dry-run
siga import_center_locations "/srv/carga-inicial/CE HABILITADOS CON GEOREFERENCIA.xlsx"
```

Los centros que en el listado de correos aparecen como `cod11674` o `ce12702` se
registran con su código oficial de cinco dígitos. Este paso no crea cuentas ni
envía correos.

## 14. Importar los informes anteriores

La carpeta ya está en `/srv/carga-inicial/informes` desde el paso 13. Solo se
importan los PDF y los archivos zip no se abren, así que descomprímalos dentro de la
carpeta antes de copiarla; las copias repetidas se detectan solas. Ejecute primero
la simulación:

```bash
siga import_historical_reports /srv/carga-inicial/informes --user <usuario-de-direccion> \
    --dry-run --report /var/tmp/simulacion-informes.csv
```

Revise el reporte. Cada informe se asigna por el código del nombre del archivo. Los
que no tienen una institución registrada quedan en `DAI-MINED` y el reporte los
marca en la columna `por_defecto`. Los de estado `error` suelen ser archivos de
más de 20 MB: comprímalos o cámbielos por una versión más liviana antes de seguir.

Cuando el reporte esté bien, ejecute la importación real:

```bash
siga import_historical_reports /srv/carga-inicial/informes --user <usuario-de-direccion> \
    --report /var/tmp/importacion-informes.csv
```

Si se interrumpe, vuelva a ejecutarla: los informes ya importados se omiten. Cada
archivo pasa por el antivirus, así que la carga completa puede tardar.

## 15. Respaldar y verificar

Haga la primera copia completa ahora que ya están los datos:

```bash
sudo systemctl start siga-mineducyt-backup.service
sudo journalctl -u siga-mineducyt-backup.service -f
siga verify_private_storage --checksums
```

La primera copia transfiere todos los archivos y puede tardar horas. La verificación
debe terminar sin archivos faltantes ni alterados. Cuando ambas terminen bien,
borre `/srv/carga-inicial`: los documentos ya están en el sistema y en el respaldo.

## 16. Probar antes de abrir

Antes de invitar a los centros, haga las pruebas de la sección
[«Pruebas antes de abrir el piloto»](production-security.md#pruebas-antes-de-abrir-el-piloto).
Las más importantes son estas:

- Enviar una invitación real a un correo de prueba y activar la cuenta.
- Subir y descargar un documento de cada tipo.
- Entrar con dos centros distintos y confirmar que ninguno ve lo del otro.
- Abrir algunos informes anteriores y comprobar que están en la institución correcta.
- Restaurar el respaldo en un equipo aparte y verificar que los archivos abren.

Anote el resultado en el registro de [verificación de una entrega](release-verification.md).

## 17. Abrir el sistema

Desde la ficha de cada centro participante, la Dirección envía la invitación. El
centro recibe un enlace que vence en 24 horas, define su contraseña y entra con su
código como usuario.

A partir de aquí siga la [operación diaria](daily-operations.md): vencimientos,
antivirus, respaldo y verificación de archivos.

## Si algo falla

| Síntoma | Qué revisar |
| --- | --- |
| El instalador se detiene en «Comprobando dependencias externas» | La línea marcada sin `[OK]`: base de datos, antivirus o correo |
| El servicio no arranca | `sudo journalctl -u siga-mineducyt.service --since today` |
| `nginx -t` falla | Las rutas del certificado y la llave |
| No llegan las invitaciones | Los datos `EMAIL_*` en `production.env` y que el servidor pueda salir al puerto SMTP |
| Una importación rechaza un archivo | La columna `detalle` del reporte CSV |

Más casos en [la guía de incidentes](incident-troubleshooting.md).
