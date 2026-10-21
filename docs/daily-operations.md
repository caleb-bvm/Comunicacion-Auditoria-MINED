# Operación diaria

Esta guía reúne las comprobaciones de seguimiento. Ejecute los comandos desde el
proyecto, con su entorno virtual y la configuración del entorno correspondiente.

## Recomendaciones vencidas

```powershell
.\.venv\Scripts\python.exe manage.py process_overdue_recommendations
```

El comando informa cuántas recomendaciones cambió a no cumplidas. Un resultado de
cero también es válido. En producción debe ejecutarse diariamente mediante la
programación descrita en [la guía de producción](production-security.md).

Revise que cada ejecución termine correctamente. Si falla, conserve el error y
resuelva la causa antes de repetirla. Compruebe en el sistema el estado y el plazo
de una recomendación afectada cuando el resultado necesite revisión.

## Evidencias pendientes de antivirus

Con el análisis antivirus habilitado:

```powershell
.\.venv\Scripts\python.exe manage.py scan_pending_evidence
```

El comando examina evidencias pendientes y aprueba las que pasan el análisis.
Informa archivos verificados y archivos pendientes o rechazados por análisis.
Si quedan pendientes, finaliza con error: revise ClamAV y los archivos involucrados.
El resultado no distingue por sí solo un archivo infectado de una falla del servicio.

## Respaldo e integridad de archivos

En producción el respaldo se ejecuta cada día y la verificación de archivos cada
semana (ver [la guía de producción](production-security.md#respaldo-y-verificación-de-archivos)).
Compruebe que ambas tareas terminen correctamente:

```bash
systemctl list-timers 'siga-mineducyt-*'
journalctl -u siga-mineducyt-backup.service -u siga-mineducyt-verify-storage.service --since "-7 days"
```

Para una verificación manual rápida (existencia y tamaño) o completa (con huellas):

```powershell
.\.venv\Scripts\python.exe manage.py verify_private_storage
.\.venv\Scripts\python.exe manage.py verify_private_storage --checksums
```

Si informa archivos faltantes o alterados, restáurelos desde el respaldo. Los
archivos sin registro no se eliminan automáticamente: revise su origen antes de
decidir.

## Registro operativo

Anote la hora de ejecución, el entorno, el resultado, la cantidad procesada y el
responsable. Guarde los errores en el registro del servicio y dé seguimiento a
los pendientes. No incluya contraseñas ni contenido de evidencias en ese registro.

## Después de una actualización

El instalador ejecuta esta comprobación y el servicio la repite en cada inicio. Para
ejecutarla manualmente en el servidor, con el mismo usuario y entorno del servicio:

```bash
sudo systemd-run --wait --pipe --collect --uid=siga-mineducyt --gid=siga-mineducyt \
    --property=WorkingDirectory=/srv/siga-mineducyt \
    --property=EnvironmentFile=/etc/siga-mineducyt/production.env \
    --setenv=DJANGO_SETTINGS_MODULE=config.settings.production \
    /srv/siga-mineducyt/.venv/bin/python manage.py deployment_preflight
```

Deben aparecer cinco resultados `[OK]`: base de datos, migraciones,
almacenamiento privado, antivirus y correo SMTP. La comprobación SMTP verifica
la conexión; la entrega real de correo requiere una prueba con una cuenta autorizada.
