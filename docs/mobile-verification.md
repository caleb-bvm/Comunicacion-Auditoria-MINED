# Revisión de la experiencia en celular

Fecha: 14 de octubre de 2026.

## Cambios

- Dirección dispone de cinco accesos inferiores. «Auditores» sigue disponible en «Más».
- El menú «Más» permite desplazarse en pantallas cortas, mantiene el foco dentro del menú y devuelve el acceso al contenido al cerrar o pasar a escritorio.
- Los controles respetan las áreas reservadas del dispositivo. Los campos usan texto de 16 px y los botones compactos tienen al menos 44 px de altura en móvil.
- Usuarios, bitácora técnica, cuentas institucionales, auditores e informes se presentan como tarjetas con etiquetas hasta 720 px. En escritorio mantienen su tabla.
- La carga múltiple organiza cada archivo en una tarjeta editable en celular, con selección, tipo, informe asociado, fecha, visibilidad y resultado.
- Las búsquedas de texto no se envían automáticamente mientras se escribe en móvil. Se aplican con el botón o con el teclado. Los selectores conservan su actualización automática.
- La paginación técnica conserva búsqueda, rol, estado y tipo de acción. Las solicitudes técnicas abren directamente su panel de atención.

## Verificación

Se utilizaron Chrome y una base PostgreSQL temporal con cuentas y documentos de demostración. Los datos de trabajo y los correos reales no participaron en las pruebas.

- Se recorrieron 25 pantallas de Dirección, Auditoría, institución y administración técnica en anchos de 320, 390, 768 y 1440 px: 100 cargas correctas, sin elementos fuera del ancho disponible ni errores de JavaScript.
- Se comprobó el menú en vertical y en horizontal a 740 × 360 px, incluido el acceso a su última opción, Tab, Shift+Tab, Escape, cierre por el fondo y cambio a escritorio.
- Se verificaron escritura sin recarga, búsqueda explícita y paginación conservando filtros.
- Se seleccionaron dos archivos, se asoció un documento a su informe, se aplicó una fecha común y se probaron edición y eliminación de filas. Esta comprobación de interfaz no guardó documentos.
- Se probaron los campos condicionales y la selección de evidencia del formulario de respuesta.
- Se inspeccionaron capturas de las tarjetas de usuarios, la carga múltiple, el menú horizontal y el formulario de respuesta.
- Se revisaron acceso, recuperación de contraseña y soporte público en 320, 390 y 768 px: nueve cargas correctas y controles dentro de la pantalla.
- La comprobación de Django terminó sin incidencias nuevas, no hay migraciones pendientes de generar y las 199 pruebas automatizadas pasaron. Se corrigió una comparación de fechas de prueba para utilizar la zona horaria de la aplicación.

Las comprobaciones se realizaron mediante emulación de tamaño en navegador. El teclado virtual, las áreas reservadas y los selectores nativos de archivos deben comprobarse también en un teléfono físico antes del piloto.
