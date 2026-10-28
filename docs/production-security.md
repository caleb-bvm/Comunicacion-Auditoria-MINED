# Despliegue seguro y operación inicial

## Alcance implementado

- Django Axes persiste intentos fallidos en la base de datos: cinco fallos por cuenta bloquean el acceso durante quince minutos. Incluye el acceso administrativo. Una autenticación correcta reinicia el contador. Producción lo activa obligatoriamente; desarrollo lo desactiva para permitir las pruebas y demostraciones habituales.
- El bloqueo es por cuenta, independientemente de IP, cookies o navegador. Nginx limita también por IP. Se silencia únicamente `axes.W006`: no se usa bloqueo global por IP en Axes para no bloquear todos los centros detrás de una misma red o proxy. No desplegar sin el límite complementario de Nginx.
- Sesiones: una hora de inactividad y máximo de ocho horas de uso; respuestas autenticadas y descargas privadas con `no-store`. Cookies de producción con prefijo `__Host-`, HTTPS y sin dominio compartido.
- Todos los campos de documentos usan el validador antivirus común. ClamAV recibe el contenido por INSTREAM, con límite de tamaño y tiempo. El archivo se acepta únicamente con una respuesta concluyente de aprobación. Si hay detección o el servicio falla, la carga se rechaza sin guardarse por el formulario.
- Informes, documentos anteriores, CDE y evidencias se vuelven a analizar al descargar, después de comprobar los permisos. Las evidencias pendientes/rechazadas conservan su bloqueo previo. Un antivirus caído o una respuesta inconclusa impiden descargar, incluso si el documento había sido aprobado antes. Los informes estadísticos y constancias generados por el sistema no son archivos subidos y conservan su flujo habitual.
- La configuración rechaza dominios comodín, URL pública sin HTTPS, correo sin cifrado, claves débiles y desactivación del antivirus. PostgreSQL remoto exige `verify-full`; solo se admite `disable` al usar loopback. `seed_demo` queda prohibido en producción.
- GitHub Actions ejecuta pruebas con PostgreSQL y revisa vulnerabilidades de dependencias en cambios a `master`.

## Preparación del servidor

Las plantillas de `deploy/` asumen Linux con systemd, Nginx, PostgreSQL y ClamAV. Son plantillas para adaptar, no una instalación ya realizada. Usar un sistema operativo con soporte y actualizaciones de seguridad. Instalar el proyecto en `/srv/siga-mineducyt`, con código propiedad de la cuenta de despliegue, no del usuario que ejecuta la aplicación.

1. Crear el usuario de servicio `siga-mineducyt`, sin inicio de sesión ni privilegios administrativos. Crear `/var/lib/siga-mineducyt/private` con propietario `siga-mineducyt`, permisos `0700`. Conceder a Nginx lectura únicamente de `staticfiles`.
2. Crear una base PostgreSQL exclusiva y una cuenta sin superusuario ni permiso de crear roles o bases. Usar una cuenta separada para mantenimiento cuando la política institucional lo permita. Nunca abrir el puerto 5432 a Internet. Para base remota, configurar certificado de servidor, CA y `POSTGRES_SSLMODE=verify-full`.
3. Instalar ClamAV y mantener sus firmas actualizadas con freshclam. Configurar clamd con `TCPAddr 127.0.0.1`, `TCPSocket 3310`, `StreamMaxLength 20M` o superior, `MaxFileSize 20M` o superior y `MaxScanSize 100M` o superior. Activar `AlertExceedsMax yes` y `AlertEncrypted yes` para no aceptar archivos que el motor no pueda inspeccionar completamente. No exponer 3310 a Internet. Si se cambia el máximo de carga, ajustar estos límites y Nginx conjuntamente.
4. Copiar `.env.example` a `/etc/siga-mineducyt/production.env`, accesible solo por administración del servidor. Generar una clave aleatoria con `python -c 'import secrets; print(secrets.token_urlsafe(64))'`; no reutilizar ejemplos. Completar dominio, SMTP y rutas. Django no carga automáticamente `.env`: systemd inyecta el archivo; para tareas manuales debe proporcionarse el mismo entorno de manera segura.
5. En el entorno virtual, instalar `requirements.txt`. Con las variables de producción cargadas, ejecutar `manage.py migrate`, `manage.py collectstatic --noinput`, `manage.py check --deploy` y `manage.py deployment_preflight`. El último comando comprueba la conexión a PostgreSQL, que no haya migraciones pendientes, escritura en el almacenamiento privado, respuesta de ClamAV y autenticación SMTP; el servicio también lo ejecuta antes de cada inicio y no arranca si alguna dependencia falla. Revisar todas las advertencias de `check --deploy`. Las de HSTS para subdominios y preload son esperadas con los valores iniciales: no activarlos hasta confirmar que todos los subdominios usan HTTPS. Después de validar el certificado, aumentar `DJANGO_HSTS_SECONDS` progresivamente a 31536000.
6. Instalar el certificado entregado por el Ministerio (certificado del servidor seguido de la cadena intermedia en un solo archivo, y su llave privada legible solo por root) y adaptar `deploy/nginx.conf`. Añadir la red VPN autorizada al bloque `/administracion/`; el acceso administrativo externo está cerrado por defecto. Verificar con `nginx -t` antes de recargar. En el firewall permitir 443 y, si se usa redirección o emisión de certificados, 80. Restringir SSH a VPN o direcciones de administración, con llaves, sin acceso directo de root. Bloquear acceso externo a 8000, 5432 y 3310.
7. Instalar `siga-mineducyt.service` y las unidades `siga-mineducyt-overdue.*` en systemd. Verificar las unidades antes de habilitarlas. Activar el servicio y el temporizador. Ejecutar una vez `siga-mineducyt-overdue.service` y comprobar el resultado y su registro. El horario es 06:15 UTC, equivalente a 00:15 en El Salvador.
8. Si hay evidencias antiguas pendientes, ejecutar `manage.py scan_pending_evidence` con el antivirus activo. El comando no aprueba archivos ante errores. Las descargas seguirán verificando su contenido.

Después de completar los requisitos anteriores, el instalador automatiza los pasos 5 a 7 y puede reutilizarse para actualizaciones:

```bash
sudo bash deploy/install-production.sh --domain DOMINIO --cert /ruta/fullchain.pem --key /ruta/privkey.pem
```

Sin `--cert` ni `--key` usa las rutas de Let's Encrypt del dominio. Debe ejecutarse con el proyecto instalado en `/srv/siga-mineducyt`. Antes de modificar servicios, se detiene si faltan el archivo de entorno, el usuario de servicio, el entorno virtual, `pg_dump` o el certificado. Antes de migrar guarda una copia de PostgreSQL en `/var/lib/siga-mineducyt/backups/pre-deploy-<fecha>.dump` y se detiene si la copia falla; al final reinicia el servicio para cargar el código nuevo. Esa copia sirve para revertir una actualización y no sustituye los respaldos externos descritos más abajo. El respaldo diario elimina las copias previas con más de 30 días (`BACKUP_PREDEPLOY_DAYS`). Si existen `/etc/siga-mineducyt/backup.env` y `/etc/siga-mineducyt/restic-password`, el instalador activa el respaldo diario; si no, lo deja desactivado y muestra una advertencia. Siempre activa la verificación semanal de archivos.

Para revertir una actualización fallida: detener el servicio, restaurar con `pg_restore --clean --if-exists --no-owner -d BASE ARCHIVO.dump`, volver a la revisión anterior del código y ejecutar de nuevo el instalador.

No servir `media` directamente desde Nginx. El proxy reemplaza las cabeceras de dirección y protocolo del visitante; Gunicorn escucha solo en `127.0.0.1`. Si se añade otro proxy o proveedor delante, revisar los límites por IP y la cadena de confianza antes de usar sus cabeceras.

## Respaldo y verificación de archivos

El sistema funciona como repositorio de los informes de la Dirección para miles de organizaciones. Un respaldo que solo copie la base de datos no basta: sin `/var/lib/siga-mineducyt/private` no se recuperan los documentos. Antes de utilizar datos reales, configurar el respaldo diario.

**Funcionamiento.** El temporizador `siga-mineducyt-backup.timer` se ejecuta a las 08:30 UTC (02:30 en El Salvador) y llama a `deploy/backup.sh` mediante `siga-mineducyt-backup.service`. El script:

1. Genera una copia de PostgreSQL con `backup-database.sh`.
2. Envía esa copia y la carpeta de archivos privados a un repositorio [restic](https://restic.readthedocs.io/). Cada instantánea contiene ambas partes; restic cifra y deduplica, así que cada noche solo transfiere los archivos nuevos.
3. Aplica la retención configurada: 14 copias diarias, 8 semanales y 24 mensuales.
4. Relee una muestra (2 %) de los datos guardados para detectar daños en el repositorio.

Primero se copia la base de datos y después los archivos. Como los documentos no se borran, cada instantánea contiene todos los archivos a los que apunta su base de datos, sin detener el servicio. Puede contener además archivos subidos durante la copia que su base de datos no conoce; `verify_private_storage` los informa como archivos sin registro.

**Configuración inicial**, como root:

1. Instalar restic desde los repositorios del sistema (`apt install restic`).
2. Preparar un repositorio **fuera del servidor**. Se recomienda un [rest-server](https://github.com/restic/rest-server) con TLS y `--append-only`: así quien comprometa el servidor de la aplicación no puede borrar los respaldos. En ese modo, usar `BACKUP_PRUNE=false` y aplicar la retención desde el servidor del repositorio. También sirve un almacenamiento compatible con S3. Si el repositorio es un disco local montado, agregar su ruta a `ReadWritePaths=` mediante `systemctl edit siga-mineducyt-backup.service`; un disco del mismo servidor no protege ante la pérdida del equipo.
3. Copiar `deploy/backup.env.example` a `/etc/siga-mineducyt/backup.env`, completarlo y crear la clave en `/etc/siga-mineducyt/restic-password` (`openssl rand -base64 48`). Ambos archivos deben pertenecer a root con permisos `0600`. **Guardar la clave también fuera del servidor**, por un canal con acceso restringido: sin ella no se puede restaurar.
4. Inicializar el repositorio: `set -a; . /etc/siga-mineducyt/backup.env; set +a; RESTIC_PASSWORD_FILE=/etc/siga-mineducyt/restic-password restic init`.
5. Ejecutar de nuevo el instalador, que activa el temporizador. Lanzar una primera copia con `systemctl start siga-mineducyt-backup.service` y revisar `journalctl -u siga-mineducyt-backup.service`. La primera copia transfiere todos los archivos y puede tardar horas.

**Verificación de integridad.** Cada domingo a las 10:00 UTC, `siga-mineducyt-verify-storage.timer` ejecuta `manage.py verify_private_storage --checksums`. El comando recorre todos los campos de archivo de la base de datos y comprueba:

- que cada archivo registrado exista;
- que conserve el tamaño registrado;
- con `--checksums`, que conserve la huella SHA-256 registrada en documentos, evidencias y adjuntos de consultas. Los informes cargados directamente en el expediente y los documentos del CDE no tienen huella; en ellos solo se verifica que existan.

Si algo falla, el comando termina con error: restaurar los archivos indicados desde el respaldo. También lista los archivos que no tienen registro en la base de datos (por ejemplo, de una carga interrumpida), sin eliminarlos. Sin `--checksums` el comando es rápido y sirve después de cualquier intervención en el disco.

**Restauración.** Para recuperar un archivo o el sistema completo:

```bash
set -a; . /etc/siga-mineducyt/backup.env; set +a
export RESTIC_PASSWORD_FILE=/etc/siga-mineducyt/restic-password
restic snapshots --tag siga-mineducyt
restic restore ID_INSTANTANEA --target /var/tmp/restauracion
```

Para una recuperación completa: detener `siga-mineducyt.service`; restaurar la base de datos con `pg_restore --clean --if-exists --no-owner -d BASE /var/tmp/restauracion/var/lib/siga-mineducyt/backups/daily/siga-mineducyt.dump`; reemplazar el contenido de `/var/lib/siga-mineducyt/private` con el de la restauración, conservando el propietario `siga-mineducyt` y los permisos `0700`; y ejecutar `verify_private_storage --checksums` antes de iniciar el servicio. Para un solo archivo, copiar únicamente la ruta que indica el comando de verificación.

Acordar con la institución la retención, la pérdida máxima tolerable (con una copia diaria es de hasta 24 horas) y el tiempo de recuperación. Restaurar una copia en un entorno aislado al menos cada trimestre y verificar expedientes, archivos y permisos: una copia sin restauración comprobada no cierra este requisito.

## Registros y soporte

systemd recoge errores de la aplicación y ejecuciones del temporizador; configurar persistencia, rotación, envío a un destino externo y alertas por caída del servicio, antivirus, firmas obsoletas, disco lleno, fallos de `siga-mineducyt-backup.service` o `siga-mineducyt-verify-storage.service` (por ejemplo, revisando `systemctl --failed`) y fallos repetidos de acceso. Restringir el acceso a los registros. Nginx no registra las rutas de activación, ya que contienen secretos; evitar también capturarlas en servicios externos de monitoreo.

Para desbloquear una cuenta tras verificar la identidad del solicitante, administración técnica puede ejecutar `manage.py axes_reset_username CODIGO`. No realizar desbloqueos masivos rutinarios. Conservar los registros según la política acordada y revisar crecimiento de tablas de Axes y sesiones. Ejecutar periódicamente `manage.py clearsessions`.

El segundo factor de autenticación no está implementado en esta entrega. Para cuentas privilegiadas, la siguiente integración recomendada es el proveedor institucional con MFA; definir primero identidad individual, enrolamiento, recuperación y revocación. El acceso técnico al servidor y a `/administracion/` debe quedar restringido por VPN mientras se concreta esa integración.

## Pruebas antes de abrir el piloto

- Enviar y recibir una invitación real con una cuenta autorizada; probar vencimiento y uso único.
- Probar certificado, redirección HTTPS, límites de acceso y recuperación tras el bloqueo. Revisar que los puertos internos no sean accesibles desde fuera.
- Probar una carga y descarga limpia de cada categoría documental. En un entorno aislado, usar el archivo de prueba oficial EICAR para comprobar detección real; detener temporalmente ClamAV y confirmar el bloqueo. No usar malware real.
- Repetir el flujo completo con dos centros distintos e intentar consultar documentos ajenos. Comprobar uso desde teléfono y red compartida.
- Ejecutar un respaldo completo, restaurarlo en un entorno aislado y pasar `verify_private_storage --checksums` sobre la copia restaurada. Verificar alertas y ejecución diaria de vencimientos.

Las pruebas locales automatizadas simulan las respuestas del antivirus. No sustituyen la prueba con ClamAV, Nginx, SMTP y PostgreSQL reales en el servidor. Las plantillas no aprovisionan automáticamente dominio, certificado, firewall, el repositorio de respaldo ni alertas.

## Referencias de implementación

Verificación local del 21 de octubre de 2026: 199 pruebas aprobadas sobre PostgreSQL; comprobación de producción sin errores y con las dos advertencias HSTS descritas arriba; `pip-audit` sin vulnerabilidades conocidas. La validación de las plantillas de `deploy/` en Linux queda pendiente del servidor de ensayo.

- [Instalación y operación de Django Axes](https://django-axes.readthedocs.io/en/latest/2_installation.html).
- [Protocolo INSTREAM de ClamAV](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
- [Lista de despliegue de Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
