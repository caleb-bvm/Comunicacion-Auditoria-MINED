# Sistema de Seguimiento de Auditoría Educativa

Primera base funcional para registrar expedientes, hallazgos, recomendaciones, respuestas institucionales, evidencias y revisiones de Auditoría Interna.

## Funciones incluidas

- Usuarios con roles y alcance por institución.
- Separación segura de la configuración de desarrollo y producción.
- Expedientes, hallazgos y recomendaciones con responsables y fechas límite.
- Respuesta estructurada por recomendación.
- Carga privada de evidencias con validación de tipo, tamaño y firma del archivo.
- Versionado de respuestas y revisión por Auditoría.
- Bitácora de envíos, revisiones y descargas.
- Panel administrativo y panel web para instituciones.
- Flujo propio para crear borradores, registrar hallazgos y recomendaciones, revisar y publicar expedientes.
- Perfil de Dirección de Auditoría con resumen ejecutivo, bandeja de decisiones, aprobación de publicaciones y cierres, y reasignación justificada de auditores.
- Indicadores operativos en el inicio de cada auditor, limitados estrictamente a sus expedientes asignados, con alertas de revisión, vencimientos y riesgo.
- Página de Análisis para Dirección centrada en todos los centros educativos, con vista nacional o filtrada por departamento y distrito, situación vigente, actividad por período, comparación territorial y centros prioritarios.
- Informe estadístico XLSX para Dirección que conserva los filtros aplicados e incluye resumen ejecutivo, gráficos, expedientes, hallazgos, recomendaciones, respuestas, prórrogas, análisis por auditor e institución, dependencias responsables, series mensuales, alertas, controles y metodología.
- Inteligencia institucional de centros educativos para Dirección, con priorización explicable, filtros territoriales y de alerta, ficha analítica por centro, estado del CDE, acceso, riesgos, obligaciones, respuestas, documentos e historial de auditoría.
- Importación validada del catálogo institucional desde CSV, incluido el distrito como dato territorial opcional.
- Repositorio de informes anteriores en PDF y Word.
- Registro de informes anteriores desde la ficha del centro, con hasta diez documentos relacionados por carga, clasificación, fechas originales, visibilidad individual y detección de archivos repetidos.
- Copia controlada y sin duplicados de recomendaciones no cumplidas o parcialmente cumplidas.
- Informes Word versionados, con aprobación directiva antes de su publicación.
- Prórrogas calculadas en días hábiles y calendario configurable de asuetos.
- Historial permanente de informes, recomendaciones y respuestas por institución.
- Separación de evidencias para impedir que una institución consulte archivos de otra dependencia.

## Inicio local en Windows

Para iniciar normalmente el proyecto y permitir el acceso desde una PC y un teléfono
Android conectados a la misma red o hotspot, use un solo comando:

```powershell
.\iniciar.ps1
```

El iniciador detecta automáticamente la dirección IPv4 activa, aplica las migraciones,
muestra los enlaces para la PC y Android, y publica el servidor en el puerto `8000`.
Si el puerto ya está ocupado, detenga el servidor anterior con `Ctrl+C` y ejecute el
comando nuevamente. La dirección puede cambiar al reconectarse al hotspot, por lo que
debe utilizar el enlace que muestre el iniciador en cada sesión.

Para la preparación inicial del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.development.example .env.development
# Complete las credenciales de PostgreSQL en .env.development
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\iniciar.ps1
```

El desarrollo utiliza PostgreSQL. La base y el usuario indicados en
`.env.development` deben existir antes de ejecutar las migraciones. El archivo
local contiene credenciales y está excluido de Git; `.env.development.example`
sirve únicamente como plantilla.

La primera ejecución de `seed_demo` genera credenciales temporales y las muestra una sola vez en la consola. Las ejecuciones posteriores actualizan los datos de ejemplo, pero conservan esas contraseñas. Para regenerarlas deliberadamente, use `python manage.py seed_demo --reset-passwords`. Solo debe utilizarse en desarrollo local.

El seed deja siete expedientes de demostración: una publicación pendiente de aprobación, tres expedientes publicados listos para respuesta institucional, una respuesta pendiente de revisión, una corrección solicitada y un cierre pendiente. Los documentos Word y las evidencias PDF asociados también se generan localmente.

Dos de los expedientes publicados se basan en los informes `IA/NA-043-2024` del Centro Escolar Florinda B. González (código 10471) e `IA/NA-046-2024` del Complejo Educativo Comunidad 10 de Octubre (código 11489). Ambos centros quedan activos en el catálogo, pero sin usuario institucional, para que la demostración incluya el flujo de activación desde el perfil de Dirección antes de presentar respuestas.

## Verificaciones

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

El vencimiento automático se ejecuta con:

```powershell
.\.venv\Scripts\python.exe manage.py process_overdue_recommendations
```

En producción, este comando debe programarse para ejecutarse una vez al día. Marca como no
cumplidas las recomendaciones pendientes o en corrección cuyo plazo vigente ya venció.

### Recordatorio obligatorio para el despliegue

- [ ] Programar `process_overdue_recommendations` para que se ejecute diariamente.
- [ ] Ejecutarlo manualmente una vez en producción y confirmar que finaliza correctamente.
- [ ] Verificar que el servidor conserve un registro de cada ejecución y de cualquier error.

El despliegue no debe considerarse terminado hasta completar estas tres comprobaciones.

## Producción

La preparación de seguridad, las plantillas de servidor y las comprobaciones previas al piloto están en [Despliegue seguro y operación inicial](docs/production-security.md). Incluyen protección de acceso, análisis antivirus de documentos y configuración de Nginx/systemd. Deben adaptarse y verificarse en el servidor antes de abrir el acceso externo.

La aplicación de producción usa `config.settings.production`, PostgreSQL y variables de entorno. Consulte [.env.example](.env.example) como inventario de configuración. El almacenamiento de evidencias debe ubicarse fuera del directorio público y conectarse con el antivirus institucional antes de habilitar descargas.

Nunca use el servidor de desarrollo ni la clave incluida en `config/settings/development.py` en un servidor institucional.

## Catálogo de centros y cuentas

Desde **Dirección → Centros → ficha del centro → Documentos e informes → Agregar informe anterior** se puede cargar un informe PDF o DOCX y sus notificaciones, respuestas, evidencias, prórrogas y cierres. El centro queda fijado por la ficha, aunque aún no tenga cuenta. Cada documento conserva su fecha original; si se desconoce, queda vacía.

En el detalle del informe se pueden agregar más documentos, registrar recomendaciones pendientes y cambiar la visibilidad. Los adjuntos compartidos solo son consultables por el centro cuando el informe principal también está compartido. La carga histórica no crea expedientes operativos, cuentas, notificaciones ni plazos de respuesta, ni altera resultados existentes. Una prórroga o respuesta antigua se conserva como documento histórico, sin ejecutarse sobre el seguimiento vigente.

En la carga individual, todos los archivos se validan antes de guardar. Se rechaza un informe idéntico ya registrado en el mismo centro o un archivo repetido dentro del mismo informe. Se conservan los originales y se registra quién cargó cada documento o cambió su visibilidad.

**Dirección y auditores** también disponen de **Informes → Carga múltiple**. Se busca el centro por código o nombre y se seleccionan o arrastran hasta 100 archivos por lote (20 MB por archivo con la configuración predeterminada). La tabla permite editar descripción, referencia, tipo, fecha original, informe y visibilidad; los valores comunes se aplican a las filas seleccionadas. Los informes principales deben marcarse como «Informe anterior» y sus documentos pueden asociarse a informes del lote o ya existentes en ese centro. La ficha del centro y el detalle de cada informe también ofrecen acceso directo.

La carga múltiple guarda primero los informes y luego sus documentos, en solicitudes independientes. Muestra el progreso y el resultado por archivo, reconoce duplicados por su contenido sin reemplazar sus datos y permite corregir o reintentar los pendientes sin repetir las cargas exitosas. Se puede pausar después del archivo actual. La página debe mantenerse abierta: los archivos pendientes no se conservan al cerrarla. Por defecto, cada archivo queda visible solo para Auditoría.

El catálogo completo se carga sin crear ni activar cuentas. Cada centro utiliza su código exacto como usuario (por ejemplo, `10471`), y conserva el correo institucional en su ficha. Dirección envía una invitación individual; el centro establece su contraseña y entonces se habilita el acceso. Consulte [el plan de catálogo institucional y cuentas](docs/user-provisioning-plan.md).

Para importar el listado oficial de correos en XLSX:

```powershell
python manage.py import_center_emails "Listado_Cuentas_Correo_CE.xlsx" --dry-run
python manage.py import_center_emails "Listado_Cuentas_Correo_CE.xlsx"
```

El archivo debe contener `Codigo de Centro Escolar`, `Nombre de Centro Escolar` y `Email Address`. La importación valida todo antes de guardar, conserva los nombres y datos territoriales ya registrados, agrega centros faltantes y actualiza los correos en las cuentas existentes. Conserva sus contraseñas y estados de acceso. Los usuarios de la antigua forma `centro.<código>` pasan al código exacto; las cuentas personalizadas de pruebas conservan su usuario. Volver a importar el mismo archivo no duplica centros ni cuentas.

Las invitaciones son de un solo uso y vencen a las 24 horas. Reenviar una invitación invalida la anterior. En desarrollo se muestran en la consola y **no se envían correos reales**. Para producción configure `PUBLIC_BASE_URL` con HTTPS, `DEFAULT_FROM_EMAIL` y los parámetros SMTP de `.env.example`; debe verificarse una entrega real a una cuenta de prueba autorizada antes de lanzar el servicio.
