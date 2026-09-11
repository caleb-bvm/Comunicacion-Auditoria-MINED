# Despliegue seguro y operación inicial

## Alcance implementado

- Django Axes persiste intentos fallidos en la base de datos: cinco fallos por cuenta bloquean el acceso durante quince minutos. Incluye el acceso administrativo. Una autenticación correcta reinicia el contador. Producción lo activa obligatoriamente; desarrollo lo desactiva para permitir las pruebas y demostraciones habituales.
- El bloqueo es por cuenta, independientemente de IP, cookies o navegador. Nginx limita también por IP. Se silencia únicamente `axes.W006`: no se usa bloqueo global por IP en Axes para no bloquear todos los centros detrás de una misma red o proxy. No desplegar sin el límite complementario de Nginx.
- Sesiones: una hora de inactividad y máximo de ocho horas de uso; respuestas autenticadas y descargas privadas con `no-store`. Cookies de producción con prefijo `__Host-`, HTTPS y sin dominio compartido.
- Todos los campos de documentos usan el validador antivirus común. ClamAV recibe el contenido por INSTREAM, con límite de tamaño y tiempo. El archivo se acepta únicamente con una respuesta concluyente de aprobación. Si hay detección o el servicio falla, la carga se rechaza sin guardarse por el formulario.
- Informes, documentos anteriores, CDE y evidencias se vuelven a analizar al descargar, después de comprobar los permisos. Las evidencias pendientes/rechazadas conservan su bloqueo previo. Un antivirus caído o una respuesta inconclusa impiden descargar, incluso si el documento había sido aprobado antes. Los informes estadísticos y constancias generados por el sistema no son archivos subidos y conservan su flujo habitual.
- La configuración rechaza dominios comodín, URL pública sin HTTPS, correo sin cifrado, claves débiles y desactivación del antivirus. PostgreSQL remoto exige `verify-full`; solo se admite `disable` al usar loopback. `seed_demo` queda prohibido en producción.
- GitHub Actions ejecuta pruebas con PostgreSQL y revisa vulnerabilidades de dependencias en cambios a `desarrollo` y `master`. El flujo comenzará a ejecutarse cuando estos archivos se publiquen en GitHub.

## Preparación del servidor

Las plantillas de `deploy/` asumen Linux con systemd, Nginx, PostgreSQL y ClamAV. Son plantillas para adaptar, no una instalación ya realizada. Usar un sistema operativo con soporte y actualizaciones de seguridad. Instalar el proyecto en `/srv/endpoint`, con código propiedad de la cuenta de despliegue, no del usuario que ejecuta la aplicación.

1. Crear el usuario de servicio `endpoint`, sin inicio de sesión ni privilegios administrativos. Crear `/var/lib/endpoint/private` con propietario `endpoint`, permisos `0700`. Conceder a Nginx lectura únicamente de `staticfiles`.
2. Crear una base PostgreSQL exclusiva y una cuenta sin superusuario ni permiso de crear roles o bases. Usar una cuenta separada para mantenimiento cuando la política institucional lo permita. Nunca abrir el puerto 5432 a Internet. Para base remota, configurar certificado de servidor, CA y `POSTGRES_SSLMODE=verify-full`.
3. Instalar ClamAV y mantener sus firmas actualizadas con freshclam. Configurar clamd con `TCPAddr 127.0.0.1`, `TCPSocket 3310`, `StreamMaxLength 20M` o superior, `MaxFileSize 20M` o superior y `MaxScanSize 100M` o superior. Activar `AlertExceedsMax yes` y `AlertEncrypted yes` para no aceptar archivos que el motor no pueda inspeccionar completamente. No exponer 3310 a Internet. Si se cambia el máximo de carga, ajustar estos límites y Nginx conjuntamente.
4. Copiar `.env.example` a `/etc/endpoint/production.env`, accesible solo por administración del servidor. Generar una clave aleatoria con `python -c 'import secrets; print(secrets.token_urlsafe(64))'`; no reutilizar ejemplos. Completar dominio, SMTP y rutas. Django no carga automáticamente `.env`: systemd inyecta el archivo; para tareas manuales debe proporcionarse el mismo entorno de manera segura.
5. En el entorno virtual, instalar `requirements.txt`. Con las variables de producción cargadas, ejecutar `manage.py migrate`, `manage.py collectstatic --noinput` y `manage.py check --deploy`. Revisar todas las advertencias. Las de HSTS para subdominios y preload son esperadas con los valores iniciales: no activarlos hasta confirmar que todos los subdominios usan HTTPS. Después de validar el certificado, aumentar `DJANGO_HSTS_SECONDS` progresivamente a 31536000.
6. Instalar un certificado válido y adaptar `deploy/nginx.conf`. Añadir la red VPN autorizada al bloque `/administracion/`; el acceso administrativo externo está cerrado por defecto. Verificar con `nginx -t` antes de recargar. En el firewall permitir 443 y, si se usa redirección o emisión de certificados, 80. Restringir SSH a VPN o direcciones de administración, con llaves, sin acceso directo de root. Bloquear acceso externo a 8000, 5432 y 3310.
7. Instalar `endpoint.service` y las unidades `endpoint-overdue.*` en systemd. Verificar las unidades antes de habilitarlas. Activar el servicio y el temporizador. Ejecutar una vez `endpoint-overdue.service` y comprobar el resultado y su registro. El horario es 06:15 UTC, equivalente a 00:15 en El Salvador.
8. Si hay evidencias antiguas pendientes, ejecutar `manage.py scan_pending_evidence` con el antivirus activo. El comando no aprueba archivos ante errores. Las descargas seguirán verificando su contenido.

No servir `media` directamente desde Nginx. El proxy reemplaza las cabeceras de dirección y protocolo del visitante; Gunicorn escucha solo en `127.0.0.1`. Si se añade otro proxy o proveedor delante, revisar los límites por IP y la cadena de confianza antes de usar sus cabeceras.

## Respaldo, registros y soporte

Antes de utilizar datos reales, habilitar respaldos cifrados fuera del servidor que incluyan PostgreSQL y `/var/lib/endpoint/private`. Para una copia consistente, detener temporalmente las escrituras durante la copia de ambos o utilizar un mecanismo coordinado de instantáneas. Respaldar los secretos por un canal separado con acceso restringido. Acordar retención, pérdida máxima tolerable y tiempo de recuperación con la institución. Restaurar una copia en un entorno aislado y verificar expedientes, archivos y permisos; una copia sin restauración comprobada no cierra este requisito.

systemd recoge errores de la aplicación y ejecuciones del temporizador; configurar persistencia, rotación, envío a un destino externo y alertas por caída del servicio, antivirus, firmas obsoletas, disco lleno, errores de respaldo y fallos repetidos de acceso. Restringir el acceso a los registros. Nginx no registra las rutas de activación, ya que contienen secretos; evitar también capturarlas en servicios externos de monitoreo.

Para desbloquear una cuenta tras verificar la identidad del solicitante, administración técnica puede ejecutar `manage.py axes_reset_username CODIGO`. No realizar desbloqueos masivos rutinarios. Conservar los registros según la política acordada y revisar crecimiento de tablas de Axes y sesiones. Ejecutar periódicamente `manage.py clearsessions`.

El segundo factor de autenticación no está implementado en esta entrega. Para cuentas privilegiadas, la siguiente integración recomendada es el proveedor institucional con MFA; definir primero identidad individual, enrolamiento, recuperación y revocación. El acceso técnico al servidor y a `/administracion/` debe quedar restringido por VPN mientras se concreta esa integración.

## Pruebas antes de abrir el piloto

- Enviar y recibir una invitación real con una cuenta autorizada; probar vencimiento y uso único.
- Probar certificado, redirección HTTPS, límites de acceso y recuperación tras el bloqueo. Revisar que los puertos internos no sean accesibles desde fuera.
- Probar una carga y descarga limpia de cada categoría documental. En un entorno aislado, usar el archivo de prueba oficial EICAR para comprobar detección real; detener temporalmente ClamAV y confirmar el bloqueo. No usar malware real.
- Repetir el flujo completo con dos centros distintos e intentar consultar documentos ajenos. Comprobar uso desde teléfono y red compartida.
- Verificar respaldo/restauración, alertas y ejecución diaria de vencimientos.

Las pruebas locales automatizadas simulan las respuestas del antivirus. No sustituyen la prueba con ClamAV, Nginx, SMTP y PostgreSQL reales en el servidor. Las plantillas no aprovisionan automáticamente dominio, certificado, firewall, respaldo ni alertas.

## Referencias de implementación

Verificación local de esta entrega: 155 pruebas aprobadas sobre SQLite; comprobación de producción sin errores y con dos advertencias HSTS descritas arriba; revisión de dependencias sin vulnerabilidades conocidas después de actualizar Django a 5.2.17. Se aplicaron las migraciones de Axes en desarrollo. La ejecución de PostgreSQL en GitHub Actions y la validación de las plantillas Linux quedan pendientes de publicación y del servidor de ensayo.

- [Instalación y operación de Django Axes](https://django-axes.readthedocs.io/en/latest/2_installation.html).
- [Protocolo INSTREAM de ClamAV](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
- [Lista de despliegue de Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
