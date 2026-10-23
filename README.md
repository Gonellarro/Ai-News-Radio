# Orquestador automático de noticias

Proyecto independiente que coordina News Radio, Ollama y Piper o Qwen TTS para producir
noticias en español, convertirlas en audio y vídeo y mantener una emisión local,
con salida opcional a YouTube mediante RTMPS.

**No hay moderación ni pasos de aprobación.** La revisión del navegador es una
observación del funcionamiento: la producción y los cambios de parrilla siguen
avanzando aunque no haya ningún navegador abierto. La salida a YouTube queda
desactivada hasta guardar una clave y solicitar el envío desde el panel.

## Qué hace automáticamente

1. Al arrancar y cada hora, solicita a News Radio revisar sus fuentes. Se respetan
   los intervalos y las pausas de cada servidor, incluidas las de Reddit.
2. Consulta la biblioteca completa y paginada de medios, Reddit, Mastodon, Bluesky
   y resultados fechados de SearXNG. Dentro de la ventana de actualidad, equilibra
   las fuentes por sus publicaciones acumuladas y elige lo más reciente de cada una.
   No usa la fecha de descarga como si fuera la de la noticia.
3. Recuerda las URLs ya procesadas. En redes utiliza el enlace externo para evitar
   repetir el mismo enlace compartido por varias cuentas. También evita titulares
   largos idénticos normalizando mayúsculas, acentos y puntuación, y extractos
   idénticos de cierta longitud aunque aparezcan en varios canales. La agrupación
   semántica de distintos artículos sobre un mismo acontecimiento queda pendiente.
4. Extrae el texto mediante News Radio; si solo hay un extracto, esa limitación se
   conserva como metadato. No descarga hilos de comentarios de Reddit.
5. Solicita una redacción en español a Ollama con las instrucciones del canal,
   directamente como texto de locución. No necesita que el borrador esté revisado.
6. Genera la locución con el motor elegido en **Configurador de locución**. Piper
   utiliza una voz fija, inicialmente Davefx en español. En Qwen elige una voz al
   azar de la biblioteca configurada para cada noticia, evitando
   repetir inmediatamente la anterior cuando hay alternativas. Guarda la elección
   antes de enviarla a Qwen y la conserva durante sus fragmentos y reintentos.
   Ollama y Qwen
   utilizan el turno compartido de IA de este PC y liberan sus modelos al terminar.
7. Recupera el MP3 y el WAV. Prepara un MP4 con el WAV, evitando una compresión de
   audio intermedia. El vídeo lleva fondo, titular, fuente y fecha de publicación.
8. Comprueba que el archivo se puede leer, lo segmenta para HLS y lo incorpora a la
   parrilla en una única transacción. Estas comprobaciones son técnicas; no hay
   evaluación ni aprobación editorial humana.
9. Busca mantener **`max_playlist` noticias activas distintas**, ordenadas por publicación.
   El balance y la IA eligen qué producir. Cada vídeo nuevo terminado sustituye
   a la noticia que lleve más tiempo en parrilla, excepto las fijadas manualmente.
   El vídeo que está sonando termina; los cambios se aplican entre piezas.
10. Reproduce la parrilla en bucle. Si todavía no hay noticias terminadas, emite una
    pantalla de continuidad, sin inventar una noticia.

## Tres proyectos y tres procesos en este

```text
news-radio:8790       Fuentes y redacción local con Ollama
qwentts:8791          Clonación de voz y audio, opcional en modo Piper
news-orchestrator:8792
  orchestrator       Descubrimiento horario, producción y panel web
  broadcaster        Reloj de emisión y publicación de segmentos HLS
  youtube            Salida independiente HLS → RTMPS, opcional
  piper_worker       Proceso temporal de voz Piper; termina tras cada locución
```

La producción de noticias es secuencial. El descubrimiento horario se ejecuta en
otro hilo y puede encontrar novedades mientras sigue una locución anterior. Se
mantienen hasta `max_pending` trabajos priorizados, contando el que se está produciendo,
además de los reintentos aplazados. Las demás candidatas quedan en estado `waiting`,
como reserva. Al completar o descartar una noticia, entra otra de esa reserva sin
esperar a la próxima búsqueda. Los excedentes se conservan en reserva.

La ventana disponible es de siete días. La selección favorece las fuentes con menos
noticias publicadas; si una no tiene candidatas utilizables, sus turnos pasan a las
demás. Dentro de una fuente se prioriza lo más reciente, con la influencia editorial
configurada. La parrilla se renueva por tiempo desde su incorporación. Si se conoce
la fecha del artículo enlazado desde una red, se usa para evitar rejuvenecer artículos
antiguos porque alguien vuelva a compartirlos. [Políticas y contadores](docs/BALANCING.md).

Los vídeos listos se conservan hasta tener un reemplazo terminado. Completar la
primera parrilla requiere generar sus audios y vídeos; no se rellenan huecos con
duplicados ni contenido inventado. Si no hay material y faltan piezas, se vuelve
a revisar la biblioteca cada cinco minutos, respetando los intervalos de consulta
de cada fuente. Al arrancar se revisa la biblioteca sin esperar a la siguiente hora.

El emisor utiliza otro contenedor. Publica en tiempo real los segmentos preparados,
sin cargar modelos ni recodificar vídeo durante la emisión. La lista HLS usa una
ventana deslizante, discontinuidades entre piezas y secuencias persistentes. No se
añade una marca de fin de emisión. El segmento ya servido se conserva mediante un
enlace físico mientras forme parte del búfer, aunque cambie la parrilla.

## Abrir la emisión

Para arrancar el conjunto en orden, desde cualquier carpeta:

```bash
/home/marti/docker/news-orchestrator/start.sh
```

El script comprueba Docker, la configuración, Ollama y el modelo editorial;
arranca News Radio, la API ligera de Qwen para gestionar su biblioteca, y finalmente el orquestador
con sus emisores. Espera a que los contenedores estén disponibles y puede solicitar
`sudo` si necesita iniciar el servicio local de Ollama. No descarga modelos.
Con `--build` reconstruye las imágenes; `--help` muestra las opciones.
El arranque reanuda la producción si `enabled` es `true`. La salida a YouTube
conserva el estado configurado. Si hay un error, se informa de la etapa y los
servicios ya iniciados permanecen disponibles para consultar el problema.

Para arrancar únicamente este proyecto manualmente:

```bash
cd /home/marti/docker/news-orchestrator
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

Panel: **http://192.168.1.62:8792** o `http://localhost:8792` desde este PC.

Pulsa **Ver emisión local**. El navegador necesita una acción para activar sonido;
esto no controla el emisor ni la producción. El flujo también puede abrirse en VLC:

```text
http://192.168.1.62:8792/live/index.m3u8
```

La primera noticia tarda lo que necesiten Ollama, Qwen y la preparación del vídeo.
El panel muestra en qué fase está cada trabajo y cuándo será la próxima búsqueda.
El reproductor tiene unos segundos de búfer respecto al emisor. Los vídeos y MP3
terminados también se pueden descargar individualmente desde la parrilla.

## Configuración editable

### Canal de YouTube

La guía paso a paso está en **http://192.168.1.62:8792/youtube-guide.html**.
Se crea el canal en YouTube y se habilitan los directos desde Studio; la primera
activación puede requerir hasta 24 horas. Para esta integración no se necesitan
credenciales de API, OAuth ni proyectos de Google Cloud: se utiliza la clave de
emisión de un directo con codificador. Usa una primera emisión oculta.

En el apartado **Salida a YouTube** del panel:

1. Pega la clave de emisión y pulsa **Guardar clave**. Esto no inicia el envío.
2. Pulsa **Enviar señal a YouTube** y comprueba la vista previa en Studio.
3. En Studio, inicia el directo si no está configurado el inicio automático.
4. **Detener envío** desactiva esta salida y su recuperación automática. No detiene
   la producción de noticias ni la emisión local.

El destino es `rtmps://a.rtmps.youtube.com:443/live2`. Se comprueba el certificado
TLS. El contenedor `youtube` copia el vídeo H.264 y reconstruye únicamente el
audio como AAC estéreo a 48 kHz, con reloj continuo entre noticias. Rellena huecos
y recorta solapamientos sin estirar la voz. El contenedor conserva el límite de
media CPU y 192 MiB; no carga modelos ni recodifica vídeo.

Un vigilante reconecta con esperas de 5, 10, 20, 40 y hasta 60 segundos. Detecta
bloqueos de 45 segundos, falta de envío de bytes, retrocesos del reloj y una
ralentización sostenida, aunque FFmpeg todavía indique progreso. Los intentos
continúan mientras el envío esté solicitado. El panel muestra ritmo y retraso
del transporte; los nuevos registros incluyen hora de Madrid y su desplazamiento
UTC explícito. Véase [YOUTUBE_CONTINUITY.md](docs/YOUTUBE_CONTINUITY.md).

La intención de emitir persiste tras reiniciar Docker. El proceso tiene un bloqueo
para evitar dos emisores simultáneos. La clave y el control se guardan en
`data/youtube/settings.json` (modo 600, carpeta 700), fuera de la imagen y de Git.
La clave no se devuelve por API, ni siquiera enmascarada parcialmente; los registros
de FFmpeg se depuran antes de guardarlos. La clave se proporciona a FFmpeg como
argumento de proceso, accesible a administradores del host. Este panel de gestión
se utiliza en la red local, sin autenticación propia.

El estado «Enviando señal» indica avance del envío, no confirma que el evento esté
público ni que haya espectadores. La visibilidad, el inicio y la finalización del
evento se gestionan en Studio. El módulo no crea ni termina eventos por API. Para
recuperar un mismo evento tras un corte conviene revisar su opción de finalización
automática. Si YouTube ya lo ha terminado, puede ser necesario crear o iniciar otro.

La emisión reenvía el bitrate variable del vídeo preparado. Si Studio avisa de
bitrate insuficiente, habrá que ajustar el perfil de codificación de los vídeos.
Las verificaciones locales de tiempos no sustituyen escuchar el canal público ni
consultar su estado en Studio mientras Qwen trabaja.

Referencias: [crear canal](https://support.google.com/youtube/answer/1646861?hl=es),
[directo con codificador](https://support.google.com/youtube/answer/2907883?hl=es),
[RTMPS de YouTube](https://developers.google.com/youtube/v3/live/guides/rtmps-ingestion),
[corrección de tiempos de FFmpeg](https://ffmpeg.org/ffmpeg.html#Advanced-options).

### `config/channel.json`

La web permite guardar motor y voz en **Configurador de locución**. La integración,
descarga de modelos y funcionamiento se describen en [PIPER.md](docs/PIPER.md).

- `enabled`: activa o pausa nuevos ciclos y trabajos; la parrilla sigue emitiendo.
- `channel_name` y `topic`: nombre y descripción del canal.
- `query`: filtro por palabras sobre la biblioteca. Vacío consulta todas las fuentes
  seleccionadas. El catálogo inicial de News Radio está dedicado a IA.
- `platform`: actualmente `all`, para medios, Reddit, Mastodon y Bluesky. Admite también `web`,
  `social`, `reddit`, `mastodon` y `bluesky`.
- `source_ids`: limita a identificadores de `news-radio/config/sources.json`.
  Vacío utiliza todas las fuentes de la plataforma seleccionada.
- `language`: `all`, `es` o `en`; idioma de las fuentes, no de la locución.
- `scan_interval_seconds`: uno de 43200 (12 horas), 21600 (6 horas), 3600
  (hora en punto) o 1800 (en punto y a y media). Se elige en el panel de control.
- `schedule_timezone`: zona del calendario; por defecto `Europe/Madrid`.
- `new_stories_per_update`: máximo de incorporaciones por actualización, actualmente
  **5**. Se producen seguidas, de una en una, y después se espera al siguiente horario.
  El nombre anterior `new_stories_per_hour` se migra conservando su valor. Los ajustes
  se aplican sin reiniciar. Véase [ROTATION.md](docs/ROTATION.md).
- `max_age_hours`: antigüedad máxima de candidatas, actualmente 168 horas. Se
  prioriza lo más reciente de cada fuente dentro de esa ventana.
- `balancing`: política modular de reparto. `strategy: "fair"` equilibra las
  publicaciones acumuladas al seleccionar candidatas; `"latest"` selecciona por
  actualidad global. `weights: {}` asigna el mismo peso a todas las fuentes.
  Los cambios se releen sin reiniciar. Véase [BALANCING.md](docs/BALANCING.md).
- `max_playlist`: objetivo y máximo de noticias terminadas en parrilla, actualmente
  20. Debe ser un entero positivo; no hay un máximo fijo de diez en el código.
- `max_pending`: trabajos priorizados de producción, actualmente 10, contando el
  que se está produciendo. Debe ser un entero positivo. Las demás candidatas quedan
  en reserva; los reintentos aplazados conservan su horario y contador por separado.
  Es independiente de `max_playlist`: no determina el tamaño de la parrilla ni
  cuántos modelos se ejecutan a la vez. La producción sigue siendo secuencial.

  Ambos valores se releen automáticamente, sin reiniciar contenedores. Al aumentar
  `max_playlist`, las piezas adicionales se generan progresivamente con las noticias
  elegibles disponibles. Al reducirlo, se retiran las sobrantes respetando el vídeo
  que está sonando y la limpieza automática de archivos.
- `tts_engine`: `piper` o `qwen`. Solo se usa un motor por trabajo.
- `piper_voice`: identificador del catálogo `config/piper_voices.json`, inicialmente
  `es_ES-davefx-medium`. Piper usa esta voz fija; no aplica el sorteo de Qwen.
- `voice_mode`: selección de voz de Qwen: `random` o `fixed`.
- `voice_name`: nombre de la voz en modo fijo, inicialmente `cristina`.
- `qwen_voice_id`: identificador estable de la voz fija, seleccionado desde la web.
  Tiene prioridad sobre `voice_name`, de modo que renombrarla no rompe la selección.
- `voice_names`: lista de nombres elegibles para el modo aleatorio. Vacía permite
  todas las voces importadas salvo las excluidas; las voces nuevas entran automáticamente.
- `voice_exclude`: nombres excluidos del sorteo; inicialmente `["qwen-demo-en"]`.
- `tts_language`: inicialmente `Spanish`.
- `audio_intro_seconds`: silencio antes de la locución, 1 segundo por defecto.
- `audio_outro_seconds`: silencio después de la locución, 2 segundos por defecto.
  Ambos admiten de 0 a 10 segundos y se aplican al MP3, al MP4 y a la emisión.
- `intro_music_enabled`: activa una intro musical elegida al azar para cada noticia
  nueva. Actualmente `true`. Los archivos se leen de `data/intros/*.mp3`.
- `voice_normalization_enabled`: iguala el volumen percibido de las locuciones,
  actualmente `true`. No modifica las referencias de las voces ni la música.
- `voice_loudness_lufs`: objetivo de sonoridad integrada, actualmente -16 LUFS.
- `voice_true_peak_dbtp`: límite de pico verdadero antes de la compresión MP3/AAC,
  actualmente -2 dBTP para dejar margen a la codificación.
- `voice_loudness_range_lu`: rango dinámico objetivo, actualmente 7 LU.

Los ajustes se releen automáticamente. Los trabajos que ya comenzaron conservan
la voz, las instrucciones y el nombre de canal usados para iniciarlos. Para otro
tema, configura también las fuentes de News Radio: cambiar solo la etiqueta
`topic` no transforma el catálogo de fuentes ni lanza una búsqueda semántica.

### `config/editorial.md`

Instrucciones de redacción de este canal, separadas de las del prototipo manual.
Se envían automáticamente al servicio de noticias y quedan guardadas con cada
borrador. La extensión inicial es de 50–80 palabras para contener la latencia de
síntesis local. Es una instrucción de estilo, no una duración exacta garantizada.

No hay un filtro editorial que detenga la producción para pedir aprobación. Los
errores de formato, conexión o generación se reintentan automáticamente, con un
límite de tres reintentos después del intento inicial. La
automatización no convierte las afirmaciones originales en hechos contrastados.
La fuente y su fecha siguen visibles en los vídeos y en el panel.

## Fallos y reinicios

- La cola, fases, identificadores remotos y resultados se guardan en SQLite.
- Los reintentos de redacción y voz llevan una clave persistente para recuperar el
  mismo trabajo si se corta la respuesta. Solo una generación que haya fallado
  explícitamente obtiene una clave nueva.
- Un reinicio retoma el trabajo en su última fase guardada. Una locución que siga
  ejecutándose en Qwen se consulta de nuevo, sin enviarla otra vez.
- Cada noticia tiene un intento inicial y como máximo **tres reintentos**. Si
  falla el intento inicial, se programa el reintento 1 a los 2 minutos; si vuelve
  a fallar, el 2 a los 4 minutos; después, el 3 a los 8 minutos. Si falla ese tercer
  reintento (cuarto fallo total), queda en estado `discarded` y sale de la cola.
  Mientras espera, otras noticias disponibles pueden procesarse.
- Un servicio ocupado (`409`) se aplaza 30 segundos sin consumir reintentos. Las
  comprobaciones de disponibilidad previas a tomar una noticia tampoco los gastan.
- El contador persiste tras reiniciar. Las noticias pendientes de una versión
  anterior que ya superen el límite también se descartan. Un trabajo que estaba
  en ejecución puede retomar su intento y terminar con sus identificadores guardados.
- Las descartadas conservan el texto, el contador y el último error en el historial,
  visibles en **Noticias descartadas por fallos**. La recopilación horaria no las
  vuelve a introducir: siguen aplicándose las mismas claves de deduplicación.
  Sus archivos temporales se limpian según la retención configurada; su registro
  sigue en SQLite. Una noticia fallida no saca vídeos buenos de la parrilla.
- La parrilla cambia cuando el MP4 y sus segmentos están completos. Si falla la
  producción, los vídeos anteriores siguen disponibles.
- El emisor continúa funcionando si se reinicia solo el orquestador.
- Las incidencias de SearXNG no detienen la reserva ni las fuentes directas. Se
  muestran en **Fuentes con incidencias**. Su instancia, consultas, categorías y
  periodicidad se configuran en `news-radio/config/sources.json` y `.env`.
- El panel muestra cuántas candidatas aportó la última revisión, cuántas fueron
  nuevas y cuántas noticias hay listas, en producción, en cola, aplazadas o en reserva.
- Se conservan MP3 y MP4; el WAV temporal del orquestador se elimina tras completar
  el vídeo. Qwen conserva su propia copia conforme a su biblioteca independiente.
- Los controles y bibliotecas de los otros dos prototipos siguen disponibles.

## Formato y recursos

### Tarjetas por fuente

Cada noticia genera una tarjeta estática con fondo, logo, titular y fecha local.
Hay tres composiciones, temas claros/oscuros y dos familias de titulares; la elección
es reproducible para cada noticia. Se ajustan el tamaño del titular y los colores
de texto a su espacio y contraste. El audio tiene prioridad: cambiar una tarjeta
reutiliza el audio ya preparado sin volver a sintetizarlo ni comprimirlo.

- Catálogo de colores y dominios: `config/visuals.json`.
- Logotipos PNG y procedencia: `data/branding/logos/`.
- Galería del canal: **http://192.168.1.62:8792/branding.html**.
- Tarjeta y diagnóstico por noticia: `poster.png` y `visual.json` en su carpeta.

Los cambios visuales se releen automáticamente y actualizan las piezas activas sin
reiniciar. Los logos se descargan una vez mediante una herramienta explícita; no se
consulta Internet al renderizar. Los dominios nuevos reciben una tarjeta por nombre
hasta incorporar su logo. Consulta [docs/VISUALS.md](docs/VISUALS.md) para ampliar las
fuentes, las composiciones y la biblioteca de recursos.

### Borrado automático de noticias retiradas

Un hilo de limpieza independiente se ejecuta al arrancar y cada 30 segundos,
incluso si la producción está pausada o Qwen está generando otra noticia. Elimina
las carpetas de noticias terminadas que han salido de la parrilla y las de trabajos
descartados o superados. Conserva las piezas activas, los trabajos pendientes y el
vídeo que el emisor esté reproduciendo hasta que termine.

La elección del siguiente vídeo y su retirada comparten un bloqueo entre procesos.
La carpeta retirada se mueve primero a `.retired-<id>` y después se elimina; una
interrupción durante el borrado se recupera en el siguiente ciclo. Los segmentos
ya publicados del HLS conservan sus enlaces físicos durante la ventana del directo,
y el emisor los borra al salir de su búfer. Esto también protege al envío a YouTube.

La limpieza solicita a Qwen eliminar todos los intentos de esa noticia mediante su
clave `orch:<id>:tts:...`: WAV, MP3, fragmentos, referencias copiadas y temporales.
Qwen conserva una fila de historial con estado `purged` y no vuelve a generar ese
identificador por una petición repetida. Los intentos remotos todavía pendientes o
en ejecución se respetan y se revisan en el siguiente ciclo. Las locuciones manuales,
la biblioteca de voces, los modelos y la carpeta original de intros se conservan.

Las dos bases de datos mantienen el historial y los identificadores para evitar
volver a producir una noticia retirada. Si Qwen no está disponible, primero se
completa el borrado local y se reintenta después su limpieza remota, sin gastar
reintentos de producción. Las incidencias aparecen en el panel y en los registros.
Se aplica también a los archivos antiguos acumulados. El antiguo ajuste
`artifact_retention_days` ya no se utiliza: no se mantiene un archivo de tres días.

### Volumen de las locuciones

Antes de añadir música o silencios, FFmpeg mide la sonoridad del WAV original de
Qwen y realiza una segunda pasada con `loudnorm`: objetivo -16 LUFS, pico máximo
-2 dBTP y rango de 7 LU. Se mide en estéreo, igual que la reproducción final.
Cuando una ganancia uniforme permite respetar los límites, se mantiene la dinámica;
si no, el filtro puede ajustar la dinámica para aproximarse al objetivo y limitar
los picos. No se trata de igualar únicamente el pico más alto.

La secuencia es **WAV de Qwen → normalizar voz → añadir intro y pausas → MP3/MP4**.
La música y los silencios no influyen en la medición de la locución. Las intros
mantienen sus niveles originales; su equilibrio es independiente. Los objetivos
se aplican al audio previo a MP3/AAC, cuyos picos pueden variar ligeramente al
comprimir. Una locución silenciosa o sin una medición válida produce un error
explícito y no sustituye los archivos de una pieza que ya está lista.

El ajuste usa FFmpeg, sin modelos de IA, y consume mucho menos que la síntesis.
Cada pieza conserva `loudness.json` con nivel de entrada, nivel de salida, modo y
tiempo de las dos pasadas. Estos niveles corresponden solo a la voz normalizada,
no al MP3 completo con música y silencios. La web muestra «Voz normalizada».

La producción nueva y el mantenimiento de la parrilla usan el mismo ajuste.
Las piezas terminadas se reconstruyen desde su WAV guardado sin repetir Ollama ni
Qwen, conservando su voz y su intro. Cambiar los objetivos en `config/channel.json`
actualiza automáticamente las piezas activas. Solo se monta una pieza cada vez;
la emisión puede terminar la versión anterior mientras se prepara la sustitución.

### Pausas entre noticias

La presentación añade un segundo de silencio antes de la voz y dos segundos finales,
manteniendo la tarjeta del titular visible. Sin música hay tres segundos añadidos
entre locuciones, además de las pausas que ya pueda contener la voz. No se atenúan ni se
recortan las últimas palabras. Se parte siempre del WAV original guardado en Qwen;
el silencio se añade antes de codificar el MP3 y el audio del vídeo.

Al cambiar estas duraciones en `config/channel.json`, un proceso de mantenimiento
actualiza únicamente las piezas terminadas de la parrilla, reutilizando sus WAV.
No vuelve a resumir, traducir ni sintetizar, ni procesa la reserva de candidatas.
La producción nueva usa los mismos ajustes. Solo se ejecuta un montaje multimedia
a la vez; los modelos mantienen su turno independiente de inferencia.

Los archivos se preparan en una carpeta temporal. Los segmentos de cada versión
tienen nombres nuevos y el manifiesto se sustituye cuando están todos preparados.
La emisión termina la versión que ya había seleccionado y utiliza la nueva en la
siguiente lectura de la pieza. Las pausas no se acumulan al reiniciar o reintentar.

### Intros musicales

Deja los MP3 cortos en `data/intros/`. Se admiten nuevos archivos sin reiniciar ni
modificar código. Al tomar una noticia de la cola se sortea una intro, evitando
repetir inmediatamente la anterior cuando hay otras válidas. No se eligen intros
para las candidatas que siguen en reserva.

La secuencia es **intro completa → silencio inicial configurado → voz → silencio
final configurado**. La música no se mezcla con la voz. Se conserva el estéreo de
la intro y ambos audios se convierten a un formato común de 48 kHz para unirlos
antes de generar el MP3 y el MP4. No se concatenan directamente los bytes de MP3.

Cada noticia conserva `intro.mp3`, `intro-selection.json` y la elección en su
historial. Esto mantiene la misma intro durante reintentos y futuros cambios de
pausas, aunque se cambie la biblioteca original. Las piezas que ya estaban listas
conservan su presentación anterior. Las intros ilegibles se omiten al sortear;
si no queda ninguna válida se registra una advertencia y se mantiene la locución
con sus pausas. Para las intros cortas se admiten archivos de hasta 20 MiB y 60 s.

MP4 H.264, 1280×720, 25 imágenes por segundo, GOP de dos segundos, audio AAC de
48 kHz estéreo a 128 kbit/s. La preparación de vídeo utiliza un hilo de FFmpeg.
La emisión HLS copia segmentos comprimidos preparados y necesita pocos recursos.

Límites de contenedor: productor 1 CPU y 512 MiB, incluido el proceso temporal de
Piper; emisor 0,5 CPU y
192 MiB. Qwen mantiene sus límites y se alterna con Ollama mediante el bloqueo ya
instalado. La capacidad sostenida depende del tiempo real de síntesis: revisar cada
hora no significa poder fabricar diez locuciones completas dentro de esa hora.

News Radio tiene ahora intervalo de recopilación de 3600 segundos en su `.env`.
Reddit conserva sus intervalos más amplios. **Revisar noticias ahora** adelanta la
consulta del orquestador, respetando los presupuestos de lectura del recolector.

## Organización y operación

```text
config/channel.json        Selección, frecuencia, voz y límites
config/editorial.md        Instrucciones del canal automático
config/piper_voices.json   Voces de Piper y descargas con revisión y SHA-256 fijos
src/news_orchestrator/
  pipeline.py              Descubrimiento y producción
  narration.py             Adaptadores Qwen/Piper y recuperación del WAV original
  piper_worker.py          Síntesis Piper en un proceso temporal de un hilo
  piper_assets.py          Catálogo y descarga explícita de voces verificadas
  client.py                Clientes HTTP de los dos servicios
  store.py                 Historial, cola, reintentos y parrilla SQLite
  balancing.py             Políticas sustituibles de reparto entre fuentes
  rotation.py              Cupo horario persistente y cadencia de producción
  media.py                 Tarjetas, MP4 y segmentación
  visuals.py               Identidades locales y elección reproducible del diseño
  cards.py                 PNG, tipografía adaptable y contraste de textos
  logo_assets.py           Importación explícita de logos fuera de la emisión
  loudness.py              Medición y normalización de voz con FFmpeg
  presentation.py          Normalización, intros, pausas y publicación de archivos
  lifetime.py              Bloqueo entre selección y retirada de archivos
  retention.py             Limpieza automática de noticias fuera de la parrilla
  broadcast.py             Emisión local independiente
  youtube.py               Salida RTMPS y reconexión independiente
  youtube_media.py         Vídeo copiado y audio con reloj continuo
  youtube_health.py        Detección de bloqueos, retraso y ralentización
  youtube_control.py       Clave privada, órdenes y estado público
  __main__.py              API y web
web/                       Panel y reproductor HLS local
data/orchestrator.sqlite3  Estado persistente
data/media/<id>/           MP3, MP4, segmentos y registros
data/hls/                  Ventana del directo local
data/youtube/              Clave, estado y registros de YouTube
```

```bash
docker compose -f compose.yaml -f compose.dev.yaml logs --tail 60 orchestrator
docker compose -f compose.yaml -f compose.dev.yaml logs --tail 60 broadcaster
docker compose -f compose.yaml -f compose.dev.yaml logs --tail 60 youtube
docker compose -f compose.yaml -f compose.dev.yaml restart orchestrator
docker compose -f compose.yaml -f compose.dev.yaml stop
```

Los cambios de Python requieren reiniciar solo el proceso afectado. HTML/CSS/JS se
ven al recargar. Para desplegar sin montar código: `docker compose up -d --build`.
Solo debe ejecutarse una instancia de cada servicio con estos datos;
hay bloqueos de proceso para evitar un doble arranque.

API: `GET /health`, `GET /api/status`, `POST /api/scan` con JSON `{}`, el flujo
`/live/index.m3u8` y archivos `/media/<id>/video.mp4` y `audio.mp3`.

YouTube: `GET /api/youtube` (estado sin clave), `GET /api/youtube/logs`,
`POST /api/youtube/key` con JSON `{"key":"..."}`, `POST /api/youtube/start` y
`POST /api/youtube/stop` con `{}`. Guardar clave no inicia la emisión.

## Siguientes etapas

1. Observar la emisión local y medir noticias completas con Cristina.
2. Afinar selección de fuentes, extensión y pronunciación en los ficheros editables.
3. Mejorar agrupación por acontecimiento, plantillas y presentación de fuentes.
4. Comprobar el directo de YouTube con una emisión oculta y ajustar el perfil
   de vídeo según las indicaciones de recepción de Studio.

Referencias: [segmentación HLS de FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#hls-2),
[hls.js](https://github.com/video-dev/hls.js). El reproductor hls.js 1.7.3 está
incluido en `web/vendor/`; su licencia Apache 2.0 se conserva junto al archivo. No depende
de un CDN en ejecución.


## Dashboard de control

La interfaz de una pantalla incluye Directo, YouTube, Noticias, Parrilla, Búsqueda y fuentes, Voces y producción y Panel de control. Consulta [la guía del dashboard](docs/DASHBOARD.md) para la edición manual de parrilla, configuración y fuentes.

### Valoración editorial opcional

En **Búsqueda y fuentes → Relevancia IA** puedes activar observación, usar las
valoraciones para seleccionar noticias o desactivar el módulo. Usa Gemma a través
de `news-radio`, comparte el turno de IA con las locuciones y limita las evaluaciones
por hora. Instalado inicialmente en observación. Consulta [la guía de relevancia](docs/RELEVANCE.md).
