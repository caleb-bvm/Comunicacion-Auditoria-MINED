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
