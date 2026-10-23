# Piper y Qwen como alternativas de locución

## Elegir motor y voz

En el panel del orquestador, **Configurador de locución** permite elegir:

- **Piper**: voz fija seleccionada en el desplegable. Inicialmente Davefx en
  español de España (`es_ES-davefx-medium`).
- **Qwen TTS**: utiliza la biblioteca de voces clonadas y mantiene los ajustes
  de voz fija o al azar del canal, configurables también desde la web.

Pulsa **Guardar motor y voz**. La configuración se escribe de forma atómica en
`config/channel.json` y se relee sin reiniciar:

```json
"tts_engine": "piper",
"piper_voice": "es_ES-davefx-medium"
```

Solo el contenedor del orquestador monta `config/` con escritura para este
configurador. Emisor y salida a YouTube mantienen el montaje de configuración de
solo lectura. El formulario modifica el motor, la voz Piper y la selección de voces Qwen.

Los trabajos iniciados fijan su motor. Al seleccionar el otro, sus trabajos
pendientes quedan en espera hasta volver a seleccionar el motor original. Un
trabajo que ya esté ejecutándose termina con el motor que tenía asignado. Las
noticias terminadas conservan su voz y no se vuelven a sintetizar por cambiar
el selector. Los trabajos antiguos con una voz o solicitud de Qwen guardada se
reconocen como Qwen para conservar su idempotencia.

## Funcionamiento y recursos

Piper se instala en la imagen del orquestador (`piper-tts==1.8.0`). No requiere
otro servicio ni el contenedor de Qwen para generar locuciones. La síntesis utiliza
un proceso temporal separado de la API. Carga la voz una vez por noticia, sintetiza
sus frases con Piper y termina, liberando la sesión ONNX y su memoria.

La sesión ONNX usa un hilo de cálculo, ejecución secuencial y espera activa
desactivada. El productor, incluida la voz Piper y los procesos de vídeo, conserva
un límite agregado de una CPU y dispone de 512 MiB de RAM. El proceso de Piper
tiene un máximo de tres minutos por intento y se termina al detener el orquestador.

Antes de cargar el modelo se obtiene el mismo bloqueo de inferencia que usan
Ollama y Qwen. Si está ocupado, se aplaza el trabajo sin consumir un fallo. No se
ejecutan modelos en el proceso de la API, del emisor ni de la salida a YouTube.

Se reutiliza la presentación habitual:

**WAV original → normalización de voz → intro → pausa inicial → voz → pausa final
→ MP3/MP4/HLS**.

Para Piper, cada noticia conserva `narration.wav` y `narration.json` con voz,
revisión, huella del texto, tiempos y pico de memoria. Un reintento reutiliza ese
WAV si coincide con el texto, la voz y el modelo. El mantenimiento visual y de
volumen puede recuperar ese original sin sintetizar otra vez. Al retirar la
noticia, se borran también esos archivos. Los modelos compartidos se conservan.

En modo Piper, los archivos locales de noticias Qwen retiradas se siguen
eliminando aunque Qwen esté apagado. La purga pendiente de sus copias remotas
se conserva para cuando vuelva a estar disponible; no bloquea las noticias Piper.
`/api/status` informa del número en `qwen_cleanup_pending`.

El motor reduce el coste de la voz. El calendario `scan_interval_seconds` y el
tamaño `new_stories_per_update` controlan los lotes, independientemente del motor:
actualmente cinco noticias seguidas en cada actualización horaria. Véase [ROTATION.md](ROTATION.md).

## Voz Davefx instalada

El catálogo está en `config/piper_voices.json`. Se utiliza una revisión fija del
[repositorio de voces Piper](https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_ES/davefx/medium):
`c10ece1aade47bb51c153c893d14e5bf8e5b7117`.

Modelo ONNX, configuración y ficha original se guardan en
`data/piper/es_ES-davefx-medium/`, fuera de Git. La descarga comprueba el tamaño y
SHA-256 de los tres archivos. Cada proceso de síntesis vuelve a comprobar sus
huellas antes de cargar el modelo. La producción habitual no descarga archivos.

Para instalarla en otra copia del proyecto:

```bash
docker compose -f compose.yaml -f compose.dev.yaml build orchestrator
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps orchestrator \
  python -m news_orchestrator.piper_assets es_ES-davefx-medium
```

Para ampliar el selector se añade una entrada al catálogo y se descarga esa voz.
Los identificadores deben coincidir con el catálogo y el idioma de la voz con
`tts_language`. No se ha implementado aún selección aleatoria de voces Piper.

## Muestra para escuchar

El configurador contiene un reproductor **Escuchar una muestra de Davefx**.
El archivo se sirve en `/samples/piper-davefx.mp3`. Es una muestra de voz aislada,
normalizada con los ajustes del canal, sin añadirla a la parrilla ni a los
contadores de noticias. Su generación no arranca el productor:

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps orchestrator \
  python -m news_orchestrator.piper_preview
```

La muestra inicial produjo 12,05 segundos de voz en 3,69 segundos de proceso Piper,
con un pico de 244,8 MiB. Incluye la carga del modelo; normalización y codificación
MP3 se realizan después. Estos valores corresponden a ese texto, no garantizan
un tiempo fijo para noticias de cualquier longitud.

## API y módulos

- `GET /api/narration`: motor y voz seleccionados, voces Piper del catálogo y
  disponibilidad de sus archivos locales. No consulta Qwen ni carga modelos.
- `POST /api/narration`: recibe exclusivamente `tts_engine` y `piper_voice`.
- `narration.py`: contrato de proveedores, selección y recuperación del original.
- `piper_worker.py`: proceso de síntesis, sin dependencias de la cola ni la web.
- `piper_assets.py`: catálogo y descarga explícita.

Referencias: [API Python de Piper 1.8.0](https://github.com/OHF-Voice/piper1-gpl/blob/v1.8.0/docs/API_PYTHON.md),
[control de hilos de ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).

## Biblioteca de voces clonadas

**Gestionar voces clonadas de Qwen** abre la web independiente de Qwen. Permite
subir una muestra con su transcripción, escucharla, cambiar el nombre, corregir
el texto, sustituir la grabación, activar/desactivar y eliminar con confirmación.
La biblioteca no carga el modelo de síntesis. `start.sh` arranca ahora esa API
ligera también cuando el canal utiliza Piper, para tener disponible su gestión.

El configurador del canal permite **Al azar entre las voces activas** o **Una voz
fija** de Qwen. Pulsa **Actualizar biblioteca** después de modificarla en la otra
pestaña. La voz fija se guarda por `qwen_voice_id` para resistir cambios de nombre;
`voice_name` sigue siendo el respaldo de las configuraciones anteriores. El modo
aleatorio respeta los filtros `voice_names` y `voice_exclude` de `channel.json`.
Si desaparece la voz fija, se elige otra activa que cumpla los filtros aleatorios.
Si no queda ninguna elegible, la producción informa del motivo.

Las locuciones ya encoladas en Qwen conservan su copia de referencia y texto,
y los audios ya producidos no se modifican al editar o eliminar una voz. Antes de
encolar, el orquestador vuelve a seleccionar si la voz elegida desapareció o fue
desactivada. Los cambios en la biblioteca no transforman las referencias en
modelos Piper: Piper continúa utilizando las voces de `piper_voices.json`.

`GET /api/narration` incluye ahora `voice_mode`, `qwen_voice_id`, `voice_name` y el
enlace a la biblioteca; `POST /api/narration` permite guardar opcionalmente los dos
primeros. `GET /api/voices` consulta la biblioteca de Qwen bajo demanda, sin cargar
modelos. Para una instalación con proxy o distinto dominio, `QWENTTS_PUBLIC_URL`
permite indicar la dirección pública de esa web en el servicio del orquestador.
