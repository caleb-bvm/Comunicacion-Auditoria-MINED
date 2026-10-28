# Verificación de una entrega

Use esta guía antes de entregar una versión de SIGA-MINEDUCYT. Registre la revisión
de Git, el entorno utilizado y el resultado de cada comprobación.

## Comprobaciones locales

Desde la carpeta del proyecto en PowerShell:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test
```

Las pruebas necesitan PostgreSQL y permisos para crear la base de pruebas. No use
credenciales de producción. Si una comprobación falla, conserve el error y corrija
la causa antes de registrar la entrega como aprobada.

## Recorrido funcional

Realice el recorrido con cuentas y documentos de prueba:

- Dirección: abrir el resumen, filtrar centros y consultar la ficha de un centro.
- Auditor: crear un borrador y revisar sus hallazgos y recomendaciones.
- Dirección: revisar la solicitud de publicación del expediente.
- Institución: consultar el expediente publicado y presentar una respuesta con evidencia.
- Auditor: revisar la respuesta y comprobar que el resultado aparece en el historial.
- Otra institución: comprobar que no puede acceder al expediente ni a su evidencia.

Verifique también el acceso desde un teléfono si la entrega incluye cambios de interfaz.

La [revisión de la experiencia en celular](mobile-verification.md) registra los ajustes
y las comprobaciones de tamaños de pantalla e interacción realizadas el 14 de octubre de 2026.

## Registro de resultado

| Dato | Valor a completar |
| --- | --- |
| Revisión de Git | Identificador del commit evaluado |
| Entorno | Local o servidor de pruebas |
| Responsable | Persona que ejecutó la revisión |
| Comprobaciones | Resultado y errores encontrados |
| Recorrido | Cuentas de prueba y resultado |
| Pendientes | Incidencias que impiden o limitan la entrega |

Para publicar en el servidor, continúe con [la guía de producción](production-security.md).
La primera instalación sigue los pasos de [despliegue inicial](initial-deployment.md).
