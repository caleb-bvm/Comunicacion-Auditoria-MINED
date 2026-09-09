# Plan de catálogo institucional y cuentas de acceso

## Decisión recomendada

El sistema debe **precargar el catálogo completo de centros educativos y dependencias**, pero **activar las cuentas institucionales solamente cuando sean necesarias**.

Las instituciones, las cuentas y las personas que integran el CDE representan objetos distintos:

- La institución debe existir desde el inicio para poder asignarle expedientes y recomendaciones, aunque todavía no tenga usuarios.
- Cada centro habilitado utiliza una cuenta institucional única que representa al centro, no a una persona particular.
- Las personas que ejercieron la administración y representación legal se registran en el historial del CDE, con su período, cargo y documento de respaldo.

Esta estrategia evita más de mil credenciales inactivas y contraseñas distribuidas anticipadamente. También evita que cada auditor tenga que volver a capturar los datos del centro y mantiene separada la actividad de la cuenta institucional del historial legal de sus administradores.

## Acceso por código e invitación

El usuario es el código exacto del centro, conservando los ceros iniciales. El correo se precarga desde el catálogo y se copia al perfil de la cuenta cuando Dirección solicita su activación. El código no se utiliza como contraseña y no se reutilizan credenciales de Dirección.

Dirección revisa el correo y solicita el envío de una invitación desde el directorio o la ficha del centro. Se crea o reutiliza una cuenta inactiva, sin contraseña utilizable. El enlace permite establecer una contraseña y habilitar el acceso; vence a las 24 horas y deja de funcionar después de utilizarlo o de reenviar la invitación. Los cambios de correo también invalidan el enlace anterior. Un fallo de envío conserva el estado previo y se muestra como error.

La ficha distingue centros sin activar, invitaciones pendientes, accesos activos y cuentas suspendidas. El centro puede consultar su correo y cambiar su contraseña desde «Mi perfil». En desarrollo los correos son simulados en la consola. La integración SMTP y la dirección HTTPS pública se configuran antes del lanzamiento.

## Distribución de responsabilidades

| Actividad | Responsable propuesto |
| --- | --- |
| Entregar y depurar el catálogo oficial | Unidad dueña del directorio de centros |
| Importar o actualizar el catálogo | Administración técnica |
| Solicitar la activación del centro | Auditor asignado o jefatura responsable |
| Crear o suspender la cuenta institucional | Administración de Auditoría |
| Registrar y mantener el CDE | Centro educativo mediante su cuenta institucional |
| Atender problemas técnicos | Administración técnica |

El auditor puede iniciar la solicitud de activación, pero no debería definir contraseñas ni crear usuarios directamente. La conformación del CDE no requiere aprobación ni mantenimiento por parte del auditor o de la Dirección de Auditoría.

## Flujo de activación bajo demanda

1. El catálogo institucional se carga desde la fuente oficial utilizando el código único del centro.
2. Al asignar la primera recomendación a un centro sin usuarios activos, el sistema debe advertirlo a Auditoría.
3. El auditor solicita la activación del centro.
4. Dirección envía una invitación al correo institucional registrado y la cuenta permanece inactiva.
5. El centro establece su contraseña mediante el enlace, habilita su acceso y utiliza la cuenta para atender expedientes y mantener el historial de su CDE.
6. La cuenta se suspende cuando el centro deja de estar activo o pierde autorización de acceso al sistema.

El flujo de activación reutiliza la cuenta del centro y rechaza crear otra si ya tiene acceso activo. Si existen varias cuentas heredadas, deben revisarse antes de habilitar una. Sus actuaciones quedan atribuidas al centro en la bitácora; cuando una actuación requiera identificar a una persona, se conserva el nombre y cargo declarado dentro de la propia actuación.

## Carga inicial

Para el piloto se recomienda:

- Importar todo el catálogo oficial disponible.
- Activar solamente entre 5 y 20 centros participantes.
- Confirmar códigos duplicados, centros cerrados y cambios de nombre antes de ampliar el uso.
- Conservar el código institucional como identificador estable; el nombre puede actualizarse.

El comando `python manage.py import_organizations archivo.csv --dry-run` valida el archivo sin modificar datos. Una vez revisado, se ejecuta sin `--dry-run` para crear o actualizar el catálogo.

Para el listado de correos en XLSX use `python manage.py import_center_emails archivo.xlsx --dry-run` y, después de revisar el resultado, ejecútelo sin `--dry-run`. Este comando agrega centros faltantes, conserva los datos existentes y actualiza correos. No crea cuentas, no activa accesos ni envía mensajes. No agrega ubicaciones que no figuren en la fuente.

Columnas admitidas:

| Columna | Obligatoria | Ejemplo |
| --- | --- | --- |
| `code` | Sí | `10754` |
| `name` | Sí | `Instituto Nacional de Nahuizalco` |
| `email` | No | `10754@clases.edu.sv` |
| `kind` | No | `educational_center` |
| `department` | No | `Sonsonate` |
| `municipality` | No | `Nahuizalco` |
| `address` | No | `Dirección institucional` |
| `is_active` | No | `true` |

## Controles necesarios antes del despliegue general

- Entregar la credencial únicamente mediante el canal oficial definido para el centro.
- Registrar creación, activación y suspensión de la cuenta institucional en la bitácora.
- Definir un tiempo máximo para atender solicitudes de acceso.
- Integrar el directorio institucional, LDAP o Active Directory cuando la infraestructura esté disponible.

## Fases propuestas

1. **Piloto:** catálogo completo y activación manual controlada de 5 a 20 centros.
2. **Expansión:** formulario interno de solicitud y activación, historial del CDE y reportes de cuentas pendientes.
3. **Operación institucional:** integración con directorio institucional y recuperación automatizada de la cuenta del centro.
