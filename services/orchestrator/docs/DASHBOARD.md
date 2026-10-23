# Dashboard del canal

## Uso

Abre http://localhost:8792 y recarga con Ctrl+F5 si conservas una pestaña del panel anterior.
La página ocupa la ventana. Los listados se paginan; los textos completos, formularios de fuentes y previsualizaciones se abren en un diálogo con su propio espacio de lectura.

- **Inicio · Directo:** reproductor local persistente, siguientes noticias, revisión manual y pausa de automatización. Pausar no detiene una locución ya iniciada ni la emisión. La revisión manual también se puede solicitar con la automatización pausada.
- **YouTube:** clave oculta, cambio guiado de clave, inicio, parada, reconexión y diagnóstico. El transporte activo no confirma que el evento público esté publicado.
- **Noticias:** biblioteca paginada con parrilla, pendientes, reserva y descartadas. Lectura, fuente, audio, vídeo e información de producción. Las candidatas solo se procesan al ser seleccionadas para la cola limitada.
- **Parrilla:** arrastrar o subir/bajar; mover a cualquier posición desde el menú de la fila; fijar, retirar y elegir próxima noticia. Guardar o cancelar explícitamente.
- **Búsqueda y fuentes:** catálogo editable de RSS, newsroom, Reddit/Mastodon mediante RSS, autores/feeds de Bluesky y consultas SearXNG; pesos, política de selección y filtro de candidatas.
- **Voces y producción:** selección de motor y voz; altas, cambios, reproducción, activación, desactivación, eliminación e importación de voces de Qwen. Piper mantiene su catálogo de voces entrenadas.
- **Panel de control:** parámetros habituales, audio, estilo editorial, catálogo visual paginado y editor completo de los valores de channel.json. Los cambios se validan y se guardan de forma atómica.

## Parrilla y automatización

La selección de noticias y el orden de reproducción son independientes. En modo manual, las nuevas noticias entran al final del orden guardado; las noticias fijadas quedan protegidas de la sustitución automática. Volver al orden automático conserva las fijaciones.

Los cambios de programación se leen entre noticias: nunca interrumpen deliberadamente el clip actual. El reproductor local y YouTube tienen búfer adicional respecto al emisor.

Una retirada manual marca la noticia para que no se reincorpore automáticamente. Su historial se conserva y sus archivos se borran mediante la limpieza existente cuando dejan de estar en uso. Solo se pueden añadir vídeos cuyos archivos sigan disponibles. Las candidatas solicitadas tienen preferencia, pero respetan max_pending, max_playlist, antigüedad y el lote de actualización disponible. No se reactivan descartadas ni se reinician sus reintentos.

No se puede reducir la capacidad por debajo de las noticias fijadas desde el dashboard. Si todas las plazas están fijadas, hay que liberar alguna para que entren nuevas noticias.

La parrilla tiene una revisión calculada sobre contenido, orden, fijaciones y próxima noticia. Si cambia mientras se edita, guardar devuelve un conflicto y exige recargar. Reordenar no aumenta los contadores históricos de publicaciones.

## Arquitectura

Frontend sin framework: módulos ES en web/modules, entrada web/app.js y estilos propios en web/dashboard.css. Las páginas auxiliares anteriores conservan styles.css. La navegación usa fragmentos de URL y un sondeo de estado cada cinco segundos; las bibliotecas se consultan de forma paginada. Las vistas se conservan al navegar para no perder formularios ni reiniciar el reproductor.

Backend: dashboard.py adapta la API; playlist_control.py concentra edición y consultas de biblioteca. balancing.py mantiene las políticas de selección y las solicitudes manuales. playlist_rotation.py renueva por tiempo en parrilla, respetando fijaciones. broadcast.py consume el orden al finalizar cada clip. SQLite añade columnas pinned, manual_excluded, requested y playlist_entered_at, y estados playlist_mode, playlist_order y next_play_id; la migración es aditiva.

news-radio sigue siendo propietario de config/sources.json. El orquestador lo consulta y modifica mediante /api/sources/config; no monta ni escribe sus carpetas. El volumen config del colector pasa a lectura/escritura para permitir esas modificaciones. Las pausas y límites de acceso siguen siendo responsabilidad del recolector.

Qwen sigue siendo propietario de su biblioteca. El dashboard delega las operaciones mediante su API; añadir voces no carga el modelo de síntesis.

## API del dashboard

GET /api/dashboard/{config,playlist,library,sources,editorial}
POST /api/dashboard/{config,playlist,request,sources,editorial}
POST /api/dashboard/voices/{add,import}
POST /api/dashboard/voices/<id>/{update,delete}
POST /api/youtube/reconnect

library acepta filter, q, page y limit. config acepta revision y changes; playlist acepta revision, ids, pinned, mode y next_id. El catálogo y el estilo editorial también incluyen revisión para impedir sobrescrituras silenciosas.

## Despliegue

Los tres servicios de emisión mantienen sus límites de recursos. El dashboard no introduce procesos de IA ni recodifica vídeo. La copia previa a esta migración se guarda en data/backups/dashboard-<fecha UTC>/ y contiene SQLite, channel.json, editorial.md y sources.json; no incluye la clave privada de YouTube.


## Apariencia del dashboard

En **Panel de control → Apariencia** se puede seleccionar Claro u Oscuro y uno de diez colores de resaltado. Los cambios son inmediatos y se guardan por navegador en `localStorage` bajo `news-radio.appearance.v1`. Las pestañas abiertas del mismo navegador se sincronizan. Las opciones de color se pueden recorrer con el teclado mediante los controles de radio nativos.

`appearance.js` gestiona las preferencias y su selector. `theme-init.js` aplica el tema antes de cargar el CSS. Los colores, superficies y estados se definen mediante variables en dashboard.css; la apariencia del dashboard es independiente de las tarjetas emitidas.

Fuentes y parrilla comparten `table-layout.js`: el número de filas se calcula a partir de la altura real del espacio de tabla. Las barras de acciones y la paginación tienen filas reservadas para que no se superpongan al cambiar el tamaño de la ventana.

## Relevancia editorial

En **Búsqueda y fuentes → Relevancia IA** se controla el evaluador opcional de
Gemma. Hay tres modos: desactivado, observación y selección. Muestra notas de 0 a
100, motivo, dimensiones y estado; permite editar criterios, pesos y presupuesto
horario. El módulo se distribuye entre `relevance.js`, la política pura, el
repositorio y el trabajador de fondo. Detalles en [RELEVANCE.md](RELEVANCE.md).


## Horario de actualización

En **Panel de control → Canal y automatización** se elige entre 12 horas, 6 horas,
una hora en punto o media hora, según la zona configurada. **Noticias nuevas por
actualización** determina el tamaño del lote serial. Los cambios se aplican sin
reiniciar. Inicio muestra el avance del lote y la siguiente revisión. Detalles
en [ROTATION.md](ROTATION.md).
