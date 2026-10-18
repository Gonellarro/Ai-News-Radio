# Qwen TTS local

Servicio independiente de clonación de voz para este PC. Incluye web, API, biblioteca
de voces, cola persistente, reproducción y descarga de MP3 y WAV.

## Diseño para este equipo

- Modelo oficial **Qwen/Qwen3-TTS-12Hz-0.6B-Base**, revisión fijada en Compose.
- CPU, dos hilos de PyTorch y cuota de dos CPU por defecto.
- Precisión `float32`, elegida después de generar audio en este i5. El intento
  inicial con `bfloat16` fue mucho más lento y se canceló. Ambas opciones son
  configurables; `float32` utiliza más memoria. No se presupone velocidad de tiempo real.
- Límite inicial de memoria de 5.500 MiB, sin swap adicional para el contenedor.
- API ligera siempre encendida. Cada fragmento carga el modelo en su propio proceso
  hijo; al guardarlo, el proceso sale y libera su memoria antes del siguiente.
- Un solo trabajo de voz en ejecución y hasta diez pendientes.
- Turno de inferencia compartido con News Radio en
  `/home/marti/docker/.ai-runtime/inference.lock`. La redacción y la síntesis se
  excluyen entre sí. Qwen descarga primero los modelos residentes de Ollama y
  comprueba que se han liberado. Las consultas directas a Ollama desde otros
  programas no participan en este turno.
- El modelo permanece en disco. La inferencia utiliza únicamente archivos locales;
  no descarga pesos ni envía el texto o la voz a un servicio externo.

La recopilación y las interfaces pueden seguir funcionando durante las locuciones.
Estos límites no garantizan por sí solos la estabilidad de una futura emisión: la
emisión y la síntesis tendrán que medirse juntas cuando se integre el directo.

## Arranque

```bash
cd /home/marti/docker/qwentts
cp -n .env.example .env
mkdir -p models voices data ../.ai-runtime
docker compose -f compose.yaml -f compose.dev.yaml build
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps qwentts python -m qwentts.download
docker compose -f compose.yaml -f compose.dev.yaml up -d
```

Abre `http://localhost:8791` o `http://IP_DE_ESTE_PC:8791`. No hace falta arrancar
otro servidor ni una sesión de Gradio. La salud de la API es independiente de que
el modelo ya esté descargado; la web muestra ambos estados.

Este Compose utiliza red del host en Linux para llegar al Ollama que escucha en
`127.0.0.1:11434`. El puerto se configura con `QWENTTS_PORT`. Si lo cambias, ajusta
también el puerto del healthcheck en Compose. No se usa el socket de Docker.

## Tu voz

Dos formas de añadirla:

1. En la web, escribe un nombre, sube la muestra y pega la transcripción exacta.
   Pulsa **Guardar voz**. Se admiten referencias de 3–30 segundos y hasta 12 MiB;
   recomendamos 6–15 segundos de una persona hablando, sin música ni ruido.
2. Copia `presentadora.wav` y `presentadora.txt` en `voices/`. El TXT debe contener
   literalmente lo que dice el audio. Pulsa **Importar carpeta** en la web. También
   admite MP3, FLAC, OGG y M4A. No modifica los originales. Los pares ya importados
   no se vuelven a importar: para una referencia nueva usa otro nombre.

La voz guardada queda normalizada a WAV mono de 24 kHz en `voices/library/`. No se
entrena un modelo nuevo: Qwen utiliza la grabación y su texto para condicionar la
locución. Para sustituir los archivos de referencia por los del otro PC, basta
traer esas muestras y sus transcripciones; no es necesario copiar su aplicación.

Se incluye como referencia inicial `qwen-demo-en.wav` y su transcripción, tomadas
del [ejemplo oficial de clonación de Qwen](https://github.com/QwenLM/Qwen3-TTS#voice-clone).
Es una voz de demostración en inglés, no la voz elegida para el canal. Su procedencia
queda aquí documentada; las voces finales las aportarás tú.

## Crear un MP3

Selecciona una voz, el idioma y escribe o pega el texto revisado. Pulsa **Generar
MP3**. Para empezar utiliza una o dos frases; después aumenta la longitud.

El trabajo aparece debajo, con estados de cola, espera de turno, carga, preparación
de la voz, locución de fragmentos y guardado. Puedes cerrar el navegador: la cola
continúa. **Cancelar** detiene el proceso y libera el turno para Ollama.

Se conservan WAV PCM de 16 bits y MP3 a 128 kbit/s. Los textos de hasta 5.000
caracteres se locutan por frases completas, una detrás de otra. Cada fragmento usa
la misma referencia de voz, sin recortarla, y queda guardado en WAV. Su proceso de
modelo termina antes de cargar el siguiente. Esto añade tiempo de carga por frase,
pero libera los pesos, las cachés y las reservas de memoria entre fragmentos.

Cuando todos están completos, un coordinador ligero une el PCM en orden, añade una
pausa breve y codifica un único MP3. Solo entonces el trabajo se marca terminado y
el orquestador puede usarlo. Un fallo no publica una noticia con audio parcial.
La continuidad de entonación entre frases y la pronunciación de nombres deben
evaluarse escuchando el resultado; esta versión no las corrige automáticamente.

### Configurar los fragmentos

En `.env`:

```dotenv
QWEN_CHUNK_MODE=sentences
QWEN_CHUNK_CHARS=160
QWEN_CHUNK_PAUSE_MS=160
QWEN_DECODE_CHUNK_FRAMES=64
```

- `sentences`: una frase completa por fragmento. Es la configuración activa.
- `characters`: agrupa frases completas hasta un objetivo de `QWEN_CHUNK_CHARS`
  caracteres. Es un objetivo flexible: una frase más larga se conserva entera.
  Nunca divide palabras para cumplir el tamaño. Se normalizan los saltos de línea
  para no cortar frases que vengan partidas; se reconocen abreviaturas habituales
  e iniciales.
- `QWEN_CHUNK_PAUSE_MS`: pausa adicional entre fragmentos, de 0 a 1.000 ms.
- `QWEN_DECODE_CHUNK_FRAMES`: ventana interna del decodificador Qwen, de 32 a 300
  frames. La versión fijada usa 300 por defecto; aquí se reduce a 64 para acotar
  las reservas temporales, manteniendo su contexto izquierdo y su unión original.
  Esta ventana no recorta el texto ni elimina audio de la referencia.

Aplicar cambios:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build qwentts
```

Cada trabajo conserva `chunks.json` con su división exacta, los WAV y métricas en
`chunks/0001/`, `chunks/0002/`, etc., y el WAV/MP3 completo en su carpeta habitual.
El progreso web indica el fragmento actual durante su carga, clonación y locución.
El pico RSS final es el máximo de los procesos de fragmento; no es una suma.
Reducir fragmentos y ventanas busca reducir picos: hay que observar las métricas
del siguiente ciclo antes de dar por resuelto el problema de memoria.

La ficha muestra duración del audio, tiempo de cálculo y pico RSS del proceso de
modelo. El tiempo de carga e importación está incluido. El consumo del contenedor
también puede incluir caché de archivos del sistema, recuperable por Linux.

### Primera locución en este PC

El 17/10/2026 se generó una locución en español con la referencia `bladerunner`
aportada en `voices/`: audio de **4,16 segundos**, **74,3 segundos** de cálculo
incluyendo la carga del modelo y **5.480 MiB de pico RSS** del proceso. El modelo
se cargó en 12 segundos. Estos datos corresponden a un texto corto y no garantizan
el tiempo ni la memoria de una noticia completa. El resultado queda disponible en
la web y en `data/jobs/4f2c48ad2b13416bb9d0b10ea12c8502/`.

## API para integrar con News Radio

News Orchestrator utiliza esta API automáticamente para convertir los guiones de
News Radio en audio. También puedes crear locuciones independientes desde esta web.

- `GET /health`: salud de la API.
- `GET /api/status`: modelo, recursos, turno y trabajos recientes.
- `GET /api/voices`: biblioteca de voces.
- `POST /api/voices`: JSON con `name`, `transcript` y `audio_base64`.
- `POST /api/voices/import`: JSON `{}` para importar parejas de `voices/`.
- `POST /api/jobs`: JSON con `text`, `voice_id` e `language` (por defecto `Spanish`).
  Devuelve `202` y el identificador del trabajo.
- `GET /api/jobs` y `GET /api/jobs/{id}`: estado y resultado.
- `POST /api/jobs/{id}/cancel`: JSON `{}` para cancelar.
- `POST /api/jobs/purge-news`: JSON `{"story_id":"<64 caracteres hexadecimales>"}`.
  Limpieza del orquestador: elimina los archivos de los intentos terminales cuya
  `request_key` empieza exactamente por `orch:<story_id>:tts:`. Devuelve cuántos
  retiró y qué intentos siguen pendientes o en ejecución. Conserva el historial
  como `purged`, incluidos los identificadores de idempotencia; no borra locuciones
  manuales, voces ni modelos. Las URLs de audio de un trabajo retirado responden 410.
- `GET /api/jobs/{id}/audio.mp3` y `audio.wav`: audio terminado, con soporte de rangos
  para reproducir y desplazarse desde el navegador.

Idiomas: español, inglés, francés, alemán, italiano, portugués, chino, japonés,
coreano y ruso. Los valores de la API usan los nombres ingleses de Qwen.

## Datos, desarrollo y mantenimiento

```text
models/                Pesos y tokenizer oficiales, descargados una sola vez
voices/                Referencias originales e importadas
data/tts.sqlite3       Cola e historial
data/jobs/<id>/         Texto y voz utilizados, progreso, log, WAV, MP3 y métricas
src/qwentts/            API, almacenamiento, voces, coordinación y proceso de modelo
web/                   Interfaz de edición y reproducción
../.ai-runtime/        Turno compartido con News Radio
```

En desarrollo el código y la web se montan desde disco:

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart qwentts
docker compose -f compose.yaml -f compose.dev.yaml logs --tail 60 qwentts
docker compose -f compose.yaml -f compose.dev.yaml stop qwentts
```

Los cambios de HTML/CSS/JS se ven al recargar. Los cambios de variables de `.env`
requieren `up -d` para recrear el contenedor. El despliegue sin montajes de código
usa `docker compose up -d --build`; los pesos, voces y audios siguen fuera de la
imagen. Las dependencias Python quedan dentro de Docker.

Un reinicio interrumpe el trabajo activo y lo marca como error; los pendientes
siguen en cola y los audios terminados se conservan. Solo debe ejecutarse una
instancia de esta API con esta base de datos. El límite inicial por trabajo es de
30 minutos, configurable con `QWEN_JOB_TIMEOUT`.

### Próximas etapas

1. Medir una locución corta y después una noticia con la voz definitiva en este PC.
2. Añadir «Generar locución» en los borradores revisados de News Radio.
3. Normalización de volumen y diccionario de pronunciación.
4. Preparación de vídeos y cola de emisión, independiente del proceso de IA.

Fuentes técnicas: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS),
[modelo Base 0.6B](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base),
[descarga del modelo de Ollama de memoria](https://docs.ollama.com/api/generate).
