# Diagnóstico de incidencias

Registre la pantalla afectada, los pasos para reproducir el problema, la hora y
el rol del usuario. Use el identificador del expediente o centro cuando corresponda.
No solicite contraseñas para investigar una incidencia.

| Síntoma | Primera comprobación | Acción |
| --- | --- | --- |
| El sistema no inicia | Mensaje del iniciador y disponibilidad de PostgreSQL | Revisar la configuración local y la conexión; repetir el inicio después de corregir la causa. |
| El teléfono no abre el sistema | Ambos dispositivos conectados a la misma red y enlace mostrado por el iniciador | Usar la dirección actual; revisar el acceso al puerto 8000 en la red local. |
| El puerto está ocupado | Existencia de un servidor anterior | Detener la sesión anterior con Ctrl+C antes de iniciar otra. |
| Una invitación no funciona | Antigüedad del enlace y existencia de un reenvío posterior | Solicitar a Dirección una nueva invitación; las anteriores quedan invalidadas al reenviar. |
| No llega un correo en desarrollo | Entorno utilizado | Consultar la consola: el desarrollo muestra los correos allí. |
| Una evidencia sigue pendiente | Estado del antivirus y resultado de scan_pending_evidence | Revisar el servicio y el archivo; repetir el análisis después de resolver el problema. |
| La importación de correos falla | Encabezados del XLSX y error de validación | Corregir el archivo y ejecutar primero import_center_emails con --dry-run. |
| Un centro no puede ver un documento histórico | Visibilidad del informe principal y del adjunto | Revisar ambas condiciones desde Auditoría antes de cambiar la visibilidad. |

## Páginas de error

Cada página de error explica a la persona qué pasó y muestra un recuadro **Datos para
soporte técnico** con el código, la dirección (sin parámetros y sin el secreto de los
enlaces de activación), la fecha y hora y, cuando existe, una referencia. Pida una
captura de ese recuadro y abra «Qué significa y qué revisar» para ver las causas
probables. Los errores 400 a 500 los dibuja Django (`apps/core/errors.py`, plantillas en
`templates/`); los de Nginx están en `deploy/errors/`.

| Código | Quién lo genera | Significado | Primera comprobación |
| --- | --- | --- | --- |
| 400 | Django | Solicitud mal formada o que supera un límite (`DATA_UPLOAD_MAX_*`, `ALLOWED_HOSTS`). | `journalctl -u siga-mineducyt --since "-15 min"` con la dirección. |
| 403 | Django | La cuenta no tiene acceso a esa acción o registro. La página muestra el motivo. | Rol, organización y asignación del expediente. |
| 403 (formulario) | Django | Falló la protección CSRF: página abierta mucho tiempo, cookies bloqueadas u origen incorrecto. | `journalctl -u siga-mineducyt \| grep "Referencia <ref>"` muestra el motivo exacto. |
| 404 | Django | La dirección no existe, el registro no existe o no está al alcance de la cuenta. | Comparar con el enlace original; los enlaces de invitación vencen a las 24 h. |
| 405 | Django | Se abrió con un enlace una acción que solo funciona desde su botón (POST). | Si ocurre al pulsar un botón del sistema, es un defecto: reportarlo. |
| 500 | Django | Excepción no controlada. La referencia identifica la traza. | `journalctl -u siga-mineducyt \| grep -A 40 "Referencia <ref>"`. |
| 413 | Nginx | El envío supera `client_max_body_size` (225 MB). No llegó a Django. | Dividir el envío; revisar el límite en `deploy/nginx.conf`. |
| 429 | Nginx | Demasiadas solicitudes desde una IP (`limit_req`). | `grep limiting /var/log/nginx/error.log`; IP compartida por NAT. |
| 502 | Nginx | Gunicorn no responde: servicio detenido, reiniciándose o sin arrancar. | `systemctl status siga-mineducyt` y `journalctl -u siga-mineducyt -n 100`. |
| 504 | Nginx | La aplicación tardó más de 180 s (`proxy_read_timeout`). | Buscar la dirección en el registro; `deployment_preflight` para BD y antivirus. |
| Sin conexión | Navegador | El dispositivo no recibió respuesta: no hay red o no llega al servidor. | Campo «Red del dispositivo»: «Sin red» es la conexión del usuario; «Conectada» apunta a DNS, firewall o Nginx. |

La página **Sin conexión** la guarda el navegador mediante un service worker (`/sw.js`), que
solo almacena esa página y sus estilos, nunca páginas ni archivos del sistema. Los service
workers exigen HTTPS o `localhost`: al abrir el sistema por IP en la red local solo aparece el
aviso inferior «Sin conexión a internet», que además detiene el envío de formularios hasta que
vuelve la conexión. El servidor no registra estos intentos.

## Fallo previo al despliegue

`deployment_preflight` identifica la dependencia que falló. Revise según su etiqueta:

- **Base de datos:** conexión, disponibilidad y credenciales del entorno.
- **Migraciones:** aplicar las migraciones pendientes mediante el procedimiento de despliegue.
- **Almacenamiento privado:** existencia de la carpeta y permiso de escritura del servicio.
- **Antivirus:** dirección, puerto y disponibilidad de ClamAV.
- **Correo SMTP:** configuración y conexión al servidor de correo.

Repita la comprobación cuando se haya corregido la causa. Consulte
[la guía de producción](production-security.md) para el procedimiento del servidor.

## Cierre de la incidencia

Registre la causa encontrada, la corrección, la revisión de Git si hubo cambios y
el resultado de repetir los pasos originales. Una incidencia queda pendiente
mientras no se pueda confirmar que el flujo afectado funciona.
