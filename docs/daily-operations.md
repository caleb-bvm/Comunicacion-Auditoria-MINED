# Operación diaria

Esta guía reúne las comprobaciones de seguimiento en el servidor. Los comandos
`siga …` ejecutan `manage.py` con el usuario y la configuración del servicio;
defina la función `siga` en la sesión como se indica en
[el despliegue inicial](initial-deployment.md#11-preparar-el-comando-de-administración).

## Recomendaciones vencidas

```bash
siga process_overdue_recommendations
```

El comando informa cuántas recomendaciones cambió a no cumplidas. Un resultado de
cero también es válido. En producción debe ejecutarse diariamente mediante la
programación descrita en [la guía de producción](production-security.md).

Revise que cada ejecución termine correctamente. Si falla, conserve el error y
resuelva la causa antes de repetirla. Compruebe en el sistema el estado y el plazo
de una recomendación afectada cuando el resultado necesite revisión.

## Evidencias pendientes de antivirus

Con el análisis antivirus habilitado:

```bash
siga scan_pending_evidence
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

```bash
siga verify_private_storage
siga verify_private_storage --checksums
```

Si informa archivos faltantes o alterados, restáurelos desde el respaldo. Los
archivos sin registro no se eliminan automáticamente: revise su origen antes de
decidir.

## Importación de informes anteriores

Los PDF de informes anteriores al despliegue pueden estar en carpetas sin orden:
el comando recorre la carpeta y sus subcarpetas y asigna cada archivo por el
código institucional escrito en su nombre (`Informe 10234 2019.pdf`,
`CE10234.pdf`, `Gestión DDE Santa Ana.pdf`). Copie los archivos al servidor en una
carpeta que pueda leer el usuario del servicio (por ejemplo `/srv/carga-inicial`)
y ejecútelo primero en simulación:

```bash
siga import_historical_reports /srv/carga-inicial/informes --user auditor.responsable \
    --dry-run --report /var/tmp/simulacion.csv
siga import_historical_reports /srv/carga-inicial/informes --user auditor.responsable \
    --report /var/tmp/importacion.csv
```

Cada informe queda como documento anterior de su institución, sin expediente,
con visibilidad «Solo Auditoría» (use `--visibility institution` para publicarlo
al centro), el nombre del archivo como descripción y registro en la bitácora. El
informe cuya institución no está en el catálogo se archiva en la Dirección de
Auditoría Interna (`DAI-MINED`), marcado como `por_defecto` en el reporte; use
`--default-code` para elegir otra institución. El reporte CSV indica el estado
de cada archivo:

| Estado | Acción |
| --- | --- |
| `importado` / `listo` | Ninguna (`listo` es el resultado de la simulación). |
| `ya_registrado` | Ninguna: el mismo archivo ya existe para la institución o se repite en otra carpeta. |
| `varios_codigos` | Dejar solo el código correcto en el nombre. |
| `error` | Revisar el detalle: archivo dañado, antivirus o tamaño mayor a `FILE_MAX_UPLOAD_MB`. |

La migración de `institutions` registra `DAI-MINED` y las catorce Direcciones
Departamentales (`DDE-AHUACHAPAN` … `DDE-LA-UNION`); los nombres con tildes,
como «DDE Cuscatlán», coinciden con su código. Las auditorías de unidades o
programas sin código quedan en `DAI-MINED`. Si el nombre trae un número de centro
que no está en el catálogo, el detalle lo indica: cargue el catálogo oficial
antes de importar para que esos informes lleguen a su centro.

Corrija los nombres y repita el comando: los archivos ya importados se omiten.
Revise una muestra de asignaciones en el reporte, porque un número del nombre
que coincida con otro código registrado asignaría el informe a esa institución.
Al terminar, ejecute un respaldo y `verify_private_storage --checksums`.

## Registro operativo

Anote la hora de ejecución, el entorno, el resultado, la cantidad procesada y el
responsable. Guarde los errores en el registro del servicio y dé seguimiento a
los pendientes. No incluya contraseñas ni contenido de evidencias en ese registro.

## Actualizar una instalación

Publique solo versiones de `master` con el CI aprobado. Con la cuenta de
administración del servidor:

```bash
cd /srv/siga-mineducyt
sudo git pull --ff-only
sudo bash deploy/install-production.sh --domain auditoria.mined.gob.sv     --cert /etc/ssl/siga/fullchain.pem --key /etc/ssl/siga/privkey.pem
```

El instalador solo ejecuta `pip` cuando cambia `requirements.txt`. Si únicamente
cambió el código, recarga Gunicorn sin cortar las solicitudes en curso: los
procesos nuevos cargan la versión actualizada y los anteriores terminan lo que
estaban atendiendo. Reinicia el servicio por completo en la primera instalación
o cuando cambian `production.env`, `requirements.txt` o la unidad de systemd.
Para forzar el reinicio, agregue `--restart`. Al final espera a que la aplicación
responda; si no lo hace en 30 segundos, muestra el registro del servicio y la
ruta de la copia previa de la base de datos.

## Después de una actualización

El instalador ejecuta esta comprobación y el servicio la repite en cada inicio. Para
ejecutarla manualmente en el servidor:

```bash
siga deployment_preflight
```

Deben aparecer cinco resultados `[OK]`: base de datos, migraciones,
almacenamiento privado, antivirus y correo SMTP. La comprobación SMTP verifica
la conexión; la entrega real de correo requiere una prueba con una cuenta autorizada.
