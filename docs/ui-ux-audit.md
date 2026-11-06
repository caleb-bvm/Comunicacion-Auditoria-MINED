# Auditoría de UI/UX — SIGA-MINEDUCYT

Fecha: 6 de noviembre de 2026. Revisión hecha sobre el entorno local con los datos de `seed_demo`, en escritorio (1366 × 768) y en teléfono (375 × 812), con las cuentas de centro educativo, auditor y Dirección.

Público principal: personal de 45 años o más, con poca práctica tecnológica en muchos casos. Los directores de centro usan sobre todo el teléfono. El sistema debe entenderse de un vistazo.

## Resumen

La aplicación funciona, pero la interfaz no ayuda a quien la usa:

- **Casi la mitad del texto mide menos de 14 px** (48 % en el inicio del centro, 56 % en el inicio de Dirección). Hay textos de 11 px y unos 25 tamaños de letra distintos en `app.css`.
- **La acción principal suele quedar escondida.** En el teléfono, la primera tarea del centro aparece después de la primera pantalla; el botón «Presentar corrección» está al final del expediente, debajo de todo el historial.
- **El estado se comunica con color y puntos sin explicación.** Una recomendación vencida se ve igual que una vigente, salvo por una barra roja.
- **No hay un sistema de diseño real.** Los tokens existen, pero conviven con 46 colores escritos a mano, 11 variantes de botón y un solo archivo de 2715 líneas.

El rediseño «SIGA-MINEDUCYT · Rediseño M3» se descarta como referencia: pule la interfaz actual sin resolver estos problemas. El nuevo diseño parte de cero.

## Hallazgos transversales

| # | Gravedad | Hallazgo | Evidencia |
|---|---|---|---|
| T1 | Alta | Texto demasiado pequeño para el público. | 48–56 % del texto visible mide menos de 14 px; `.7rem` (11 px) aparece 17 veces. Etiquetas de campo en 12 px y negrita. |
| T2 | Alta | El estado depende del color. | Chips con un punto genérico; barras laterales rojas, marrones o azules sin leyenda; un plazo vencido se muestra como una fecha neutra («04/10/2026») sin la palabra «Vencida». |
| T3 | Alta | Controles nativos en inglés y vacíos. | El campo de archivos dice «Choose Files / No file chosen»; las listas desplegables empiezan con «---------». |
| T4 | Media | Demasiados botones rellenos. | El inicio del auditor tiene un botón relleno por fila; Dirección muestra 3 rellenos y 8 contorneados en la misma vista. Se pierde la «siguiente acción». |
| T5 | Media | La fuente declarada no se carga. | `Roboto Flex` no está en `static/` ni se enlaza: en Windows se ve Segoe UI y en cada equipo una distinta. |
| T6 | Media | Foco de teclado poco visible. | `outline: 3px solid rgba(36,87,166,.3)`: el azul al 30 % no llega a 3:1 sobre blanco. |
| T7 | Baja | Enlaces de texto con área táctil pequeña. | «Ver expedientes» y «Ver todos» miden 24 px de alto (mínimo recomendado: 48 px). |
| T8 | Estructural | No hay sistema de diseño. | 46 hexadecimales literales pese a 42 variables; 11 clases de botón; todo en `static/css/app.css`. |

## Centro educativo

| # | Gravedad | Hallazgo |
|---|---|---|
| C1 | Alta | En el teléfono, la primera recomendación por atender empieza a 987 px: la cabecera de bienvenida y cuatro indicadores llenan la primera pantalla. |
| C2 | Alta | En un expediente que «Requiere corrección», el botón «Presentar corrección» está casi al final de la página (2625 de 2789 px), después de todas las versiones. El comentario del auditor que explica qué corregir queda enterrado en el historial. |
| C3 | Media | El formulario «Presentar respuesta» no avisa que el plazo ya venció, dice «Se aplica el límite configurado por archivo» sin decir cuál es, y el botón «Enviar respuesta» se parte en dos líneas, con «Cancelar» encima. |
| C4 | Media | En «Mis expedientes», el título de cada tarjeta repite el nombre del propio centro; el asunto real del expediente va en gris pequeño. |
| C5 | Baja | El código del expediente se estira a todo el ancho en «Expedientes recientes». |
| C6 | Baja | «Consultas» no está en la barra inferior del teléfono; queda dentro de «Más». |

## Auditor

| # | Gravedad | Hallazgo |
|---|---|---|
| A1 | Alta | «Siguiente trabajo pendiente» no dice qué recomendación ni qué hay que hacer: hay filas idénticas («IA/NA-010-2025 · Instituto Nacional de Nahuizalco») y todas llevan a «Abrir expediente», no a la tarea. |
| A2 | Alta | «Revisar respuesta» no muestra la recomendación ni la documentación requerida junto a la respuesta: el auditor compara de memoria. |
| A3 | Media | La cartera de expedientes usa tarjetas grandes: caben dos por pantalla. Para comparar plazos y estados sirve más una lista ordenada por plazo. |
| A4 | Media | Los plazos vencidos no se distinguen en la lista de expedientes. |

## Dirección

| # | Gravedad | Hallazgo |
|---|---|---|
| D1 | Media | El menú lateral tiene 14 entradas en cuatro grupos y necesita desplazamiento propio en una pantalla de 768 px. |
| D2 | Media | «Requiere su atención» mezcla cinco tipos de aviso (cierre, publicación, sin actividad, respuesta pendiente, acceso vencido) con barras de color sin leyenda y nombres de centro en MAYÚSCULAS. |
| D3 | Media | En «Análisis», antes del primer número hay 8 chips de prioridad, 3 filtros y «Más filtros». Seis de los ocho chips son rojos o naranjas, así que la alarma pierde valor. La tabla por departamento usa texto de 12 px. |

## Ingreso

| # | Gravedad | Hallazgo |
|---|---|---|
| I1 | Media | En una ventana de 800 px, el formulario de ingreso queda debajo de una portada con tres tarjetas de roles. Quien entra solo quiere escribir su usuario y contraseña. |

## Dirección del nuevo diseño

El nuevo sistema se diseña desde cero en Material Design 3 (Material You), con estas reglas pensadas para el público:

1. **Lectura cómoda.** Texto base de 18 px; nada por debajo de 14 px. Etiquetas encima del campo, sin dos puntos.
2. **Una pantalla, una tarea.** Cada pantalla abre con lo que hay que hacer y un solo botón relleno. Los datos de apoyo van después.
3. **El estado se lee de tres formas a la vez:** color, ícono y palabra. Los plazos dicen «Vence en 3 días» o «Venció hace 5 días», no solo la fecha.
4. **Objetivos táctiles de 48 px** y botones de 48 px de alto.
5. **Palabras simples** y verbos claros: «Responder», «Corregir», «Enviar a revisión».
6. **Nada escondido en el teléfono:** las tareas del día primero, la navegación principal siempre visible.
7. **Método técnico tomado de Rentavía:** roles de color generados desde una semilla con Material Color Utilities, Roboto Flex y Material Symbols Rounded servidos desde `static/`, capas de estado de M3, y `tokens.css` + `components.css` sin paso de compilación.

## Próximos pasos

1. Diseñar el sistema y las pantallas clave en un artefacto de diseño (en curso).
2. Construir `tokens.css`, `components.css`, los parciales de Django y una página `/dev/ui/` solo para desarrollo.
3. Migrar por flujo, empezando por la respuesta del centro educativo, luego la revisión del auditor y las decisiones de Dirección.
