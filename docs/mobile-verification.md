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

- ~~Las páginas de error 403, 404 y 500 usan las plantillas predeterminadas de Django, sin `viewport`, y en celular se muestran a 980 px de ancho.~~ Resuelto: ver «Páginas de error y selector de archivos».
- ~~El campo de documentos de respaldo del formulario de respuesta no declara los formatos admitidos (`accept`), por lo que el selector del teléfono no los filtra.~~ Resuelto: ver «Páginas de error y selector de archivos».
- ~~La tabla territorial de Análisis se desplaza horizontalmente en celular. Falta decidir si se presenta como tarjetas por territorio.~~ Resuelto: ver «Análisis territorial en tarjetas».
- Sigue pendiente la prueba en un teléfono físico descrita en la revisión anterior.

## Páginas de error y selector de archivos

Fecha: 28 de octubre de 2026.

### Cambios

- Las páginas 400, 403, 404 y 500 y el rechazo por formulario vencido (CSRF) usan el diseño del sistema, con `viewport`, mensaje en español y un acceso al inicio. Con sesión iniciada conservan la navegación. La página 403 muestra el motivo indicado por el sistema, por ejemplo «Esta acción corresponde al personal auditor autorizado.». Ninguna usa `{% url %}`, para que sigan funcionando aunque falle la configuración de direcciones.
- El procesador de contexto de la barra lateral admite solicitudes sin usuario. Sin ese ajuste, una página 400 producida antes de la autenticación (por ejemplo, un dominio no autorizado) fallaba al renderizarse.
- Los campos de archivo que usan el validador de evidencias declaran los formatos admitidos con `accept`: documentos de respaldo de la respuesta, adjuntos de consultas, documentos de informes anteriores, acta del CDE y documento de salida de integrantes. El valor se obtiene de `ALLOWED_EXTENSIONS`, por lo que el selector y la validación del servidor no pueden diferir. El servidor sigue validando cada archivo.

### Verificación

- Nueve pruebas automatizadas cubren las cinco páginas de error y los formatos de cada campo de archivo. La comprobación de Django terminó sin incidencias, no hay migraciones pendientes de generar y las 221 pruebas pasaron.
- En el navegador integrado, a 360 y 1440 px, la página 403 de un centro educativo se mostró sin desbordes y con la barra inferior. Los selectores de la respuesta y de la nueva consulta declaran los formatos y la respuesta conserva la selección múltiple.
- Las páginas 404 y 500 solo se verificaron con las pruebas, porque el modo de desarrollo muestra en su lugar la página de diagnóstico de Django.

## Tablas como tarjetas en celular

Fecha: 29 de octubre de 2026.

### Cambios

- Siete tablas que se desplazaban horizontalmente en celular se presentan como tarjetas con etiquetas hasta 720 px, con el mismo mecanismo de las listas de usuarios, bitácora, cuentas, auditores e informes: cartera e historial de cartera del auditor, expedientes, respuestas e historial de auditores del centro educativo, vista previa de la operación masiva de cartera e historial administrativo de una cuenta. En escritorio conservan su tabla.
- Las tarjetas también admiten celdas de encabezado de fila (`<th scope="row">`), subtítulos de tabla y las tablas del perfil del centro, que antes imponían un ancho mínimo de 760 px y su propio relleno.
- En la cartera del auditor, el control «Seleccionar toda la página» de la cabecera queda oculto en las tarjetas. En celular se muestra un control equivalente junto a las acciones masivas, sincronizado con el de la cabecera, y cada tarjeta etiqueta su casilla como «Seleccionar». Las casillas de las tarjetas miden 24 px.
- Entre 721 y 900 px, los botones dentro de las tablas se partían letra por letra, por ejemplo «Asignar» en la cartera del auditor. Ahora conservan su texto en una línea.

### Verificación

- En el navegador integrado se revisaron las siete tablas en 320, 390, 768 y 1440 px, sin desbordes. En 768 px las tablas del perfil del centro se desplazan dentro de su contenedor, como antes; las tarjetas empiezan en 720 px.
- Se comprobó la selección de la cartera desde el control móvil y desde la cabecera: todas, una menos (estado intermedio en ambos controles) y ninguna. La vista previa de la operación masiva se abrió sin confirmar el cambio.
- Se repitió en 320 px la revisión de las listas que ya usaban tarjetas y de otras pantallas con botones en tablas, sin desbordes.
- Dos pruebas automatizadas comprueban que las siete tablas se renderizan como tarjetas y que existe el control de selección móvil. La comprobación de Django terminó sin incidencias, no hay migraciones pendientes de generar y las 223 pruebas pasaron.

## Análisis territorial en tarjetas

Fecha: 29 de octubre de 2026.

### Cambios

- Hasta 720 px, la tabla «Estado por departamento» o «Estado por distrito» de Análisis se presenta como una tarjeta por territorio. El nombre del territorio, con sus expedientes y obligaciones, es el título de la tarjeta. Debajo aparecen centros, cobertura, atención inmediata, vencimientos y cumplimiento, y al final «Ver distritos» o «Ver centros». Un territorio sin enlace, como «Sin departamento registrado», no muestra la fila de acción. En escritorio se mantiene la tabla.
- La presentación es solo visual: los valores siguen saliendo del mismo servicio que el XLSX (`territorial_analysis.py`).
- Los textos de la tabla usan singular cuando corresponde: «1 expediente · 1 obligación» y «1 auditado» en lugar de «1 expedientes · 1 obligaciones» y «1 auditados».

### Verificación

- En el navegador integrado se revisó la agrupación por departamento en 320, 390, 768 y 1440 px y la agrupación por distrito de San Salvador en 320 px, sin desbordes. En 768 y 1440 px la tabla conserva su desplazamiento horizontal dentro del contenedor, como antes.
- Una prueba automatizada comprueba la marca de tarjetas y los textos en singular y plural. La comprobación de Django terminó sin incidencias, no hay migraciones pendientes de generar y las 224 pruebas pasaron.
