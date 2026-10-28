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

## Revisión posterior al rediseño institucional

Fecha: 28 de octubre de 2026.

El rediseño Material 3 cambió la hoja de estilos, la plantilla base y el acceso después de la revisión anterior. Se repitió el recorrido en celular y se corrigieron las regresiones encontradas.

### Cambios

- Análisis ya no se ensancha a 1012 px en celular. El texto oculto «Acción» de la tabla territorial usa posición absoluta y escapaba de su contenedor con desplazamiento, lo que ampliaba la página y arrastraba la barra inferior. Los contenedores de tablas ahora contienen ese texto.
- El icono activo de la barra inferior vuelve a medir 24 px. El relleno de la píldora lo reducía a 16 px. En pantallas de 360 px o menos la píldora mide 52 px y las opciones no usan relleno lateral, para que el icono y la etiqueta «Expedientes» no excedan su espacio.
- El selector «Estado actual / Actividad por período» de Análisis mantiene las dos opciones lado a lado en celular. Al apilarse formaba una píldora de 105 px de alto.
- En el historial institucional, «Recomendaciones» se salía de su tarjeta en pantallas de 360 px. Hasta 380 px las tres cifras se presentan como filas con etiqueta y valor.
- En Decisiones, las pestañas ensanchaban la columna y las tarjetas quedaban a 3 px del borde derecho en 320 px. La columna ya no se ajusta al contenido y los contadores de las pestañas son más compactos hasta 360 px.
- Se actualizó la versión de la hoja de estilos para que los teléfonos no conserven la anterior en caché.

### Verificación

Se utilizó el navegador integrado con la base PostgreSQL de desarrollo y las cuentas de demostración, mediante sesiones de prueba creadas para la revisión y eliminadas al terminar. No se enviaron formularios ni se modificaron datos.

- Se recorrieron 42 pantallas: 16 de Dirección, 7 de Auditoría, 10 del centro educativo, 6 de administración técnica y 3 públicas (acceso, restablecimiento y soporte).
- En 320 px se revisaron las 42 pantallas, después de las correcciones. Se comprobó por programa que ningún elemento saliera del ancho de la pantalla ni del contenedor que lo incluye, fuera de las áreas con desplazamiento propio.
- En 390 px se revisaron 38 pantallas, en 768 px 28 de los cuatro roles y en 1440 px 18. En 390 px se comprobó el ancho de la pantalla. En 768 y 1440 px, el ancho de la pantalla y, en las pantallas del centro educativo y de Auditoría, también los contenedores.
- Se inspeccionaron capturas de la mesa de trabajo, el expediente, Análisis, el detalle de centro, Decisiones, el historial, el CDE, el formulario de respuesta, la revisión de respuestas, el menú «Más» y el acceso.
- La consola no registró errores de JavaScript. Solo aparecieron los dos 403 esperados al abrir pantallas con un rol sin permiso.
- La comprobación de Django terminó sin incidencias, no hay migraciones pendientes de generar y las 212 pruebas automatizadas pasaron.

### Pendiente

- Las páginas de error 403, 404 y 500 usan las plantillas predeterminadas de Django, sin `viewport`, y en celular se muestran a 980 px de ancho.
- El campo de documentos de respaldo del formulario de respuesta no declara los formatos admitidos (`accept`), por lo que el selector del teléfono no los filtra.
- La tabla territorial de Análisis se desplaza horizontalmente en celular. Falta decidir si se presenta como tarjetas por territorio.
- Sigue pendiente la prueba en un teléfono físico descrita en la revisión anterior.
