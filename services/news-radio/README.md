# News Radio

Proyecto independiente para preparar un canal informativo sobre inteligencia artificial.

## Alcance inicial

El prototipo reúne titulares y extractos de fuentes de IA, conserva su procedencia y permite revisar una bandeja local. Las fuentes directas son la base; SearXNG es un complemento opcional. Incluye redacción manual de borradores en español con Ollama local. Voz, vídeo y publicación automática quedan para etapas posteriores.

Temas iniciales:

- Productos y modelos de IA.
- Investigación y ciencia.
- Seguridad, sociedad y regulación.

La ingesta directa revisa las fuentes al arrancar y cada 30 minutos, consultando solo las que han cumplido su intervalo. Reddit utiliza intervalos más conservadores. Guarda título, extracto, URL, fuente, fecha de publicación y fecha de detección en `data/news.sqlite3`. La actualización manual se solicita desde el panel y respeta los plazos guardados. Una fuente averiada conserva sus noticias anteriores y no bloquea a las demás. Las URLs repetidas se guardan una vez, conservando sus fuentes de origen; agrupar distintas URLs sobre un mismo hecho queda pendiente.

## Fuentes iniciales para evaluar

La lista es una propuesta, no una autorización para republicar contenidos. En la primera fase se guardarán metadatos y enlaces; el canal debe narrar resúmenes propios con atribución, no leer artículos completos.

El catálogo editable está en [`config/sources.json`](config/sources.json). Se monta en Docker desde `config/` y se relee en cada recopilación, sin reconstruir la imagen. Para retirar una fuente, cambia `enabled` a `false`; sus noticias dejan de mostrarse y su historial se conserva. Para añadir un RSS, agrega un objeto con un `id` único, nombre, URL, idioma, tipo y un `feed_url` RSS o Atom válido. Para el conector RSS, `feed_url: null` significa **pendiente de conectar**. Las fuentes Bluesky usan `actor` o `feed` en lugar de `feed_url`. Después de editar, pulsa **Actualizar fuentes** o espera la revisión periódica.

### Fuentes primarias

- OpenAI News, Google AI, DeepMind y Hugging Face: feeds verificados.
- arXiv Machine Learning: feed verificado; es un repositorio de investigación, no un medio periodístico. Puede devolver cero entradas.
- Anthropic Newsroom: pendiente de una vía directa validada.

### Cobertura independiente

- MIT Technology Review, The Verge y Xataka (IA, en español): feeds verificados.
- Associated Press y Reuters: pendientes de una vía directa validada.

La lista completa y sus direcciones viven en el catálogo. `topics` describe la temática de la fuente; `type` distingue fuentes primarias, medios independientes y repositorios de investigación. El panel muestra el estado y la última lectura de cada una.

### Redes y comunidades

El catálogo incluye cuatro comunidades de Reddit, tres cuentas y dos etiquetas de Mastodon, y tres cuentas y dos feeds temáticos de Bluesky. La selección, su propósito, los filtros y las limitaciones de acceso se detallan en [`docs/SOCIAL_SOURCES.md`](docs/SOCIAL_SOURCES.md).

El filtro **Contenido** permite consultar las redes por separado. Sus publicaciones conservan autor y enlace compartido cuando están disponibles y se muestran como **por contrastar**. La vista predeterminada sigue mostrando medios y fuentes oficiales. Los límites HTTP 429 se respetan incluso al pulsar **Actualizar fuentes**.

## Desarrollo con Docker

Requiere Docker y el plugin Docker Compose.

```bash
cd /home/marti/docker/news-radio
cp -n .env.example .env
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

Abre `http://localhost:8790`. Por defecto muestra las noticias guardadas de las fuentes directas: deja el texto vacío para verlas todas o filtra por palabras, fuente, periodo e idioma. Las consultas a esta bandeja no contactan con SearXNG. Los textos originales no se traducen y la búsqueda local trabaja sobre titulares y extractos.

En Linux, el contenedor **de desarrollo** utiliza la red del host para alcanzar Ollama en `127.0.0.1:11434`, aunque Ollama solo escuche en localhost. La web mantiene el puerto `NEWS_RADIO_PORT` (8790). Este override requiere una versión de Docker Compose que admita `!reset`. La configuración de despliegue mantiene red bridge; allí `OLLAMA_URL` debe apuntar a un servidor accesible desde el contenedor (por defecto `host.docker.internal:11434`). La dirección loopback dentro de una red bridge apunta al propio contenedor. No hace falta modificar tu servicio Ollama para el desarrollo local en Linux.

El periodo se aplica a la fecha de publicación, nunca a la fecha de descarga o de actualización. Las entradas sin fecha se excluyen cuando se pide un periodo y se muestran como **Fecha sin verificar** al elegir **Sin límite temporal**. El panel indica cuántas quedaron excluidas. Se recuperan hasta 200 entradas por fuente y se muestran hasta 100 resultados por página. `GET /api/news` admite `offset` y `limit` (1–100), para que el orquestador pueda recorrer toda la biblioteca sin que los primeros cien resultados oculten otras fuentes.

La frecuencia se configura con `NEWS_RADIO_REFRESH_SECONDS` (1800 por defecto). El código local se monta en el contenedor de desarrollo; tras modificar Python, aplica `docker compose -f compose.yaml -f compose.dev.yaml restart news-radio`. Los cambios en HTML/CSS/JS se ven al recargar.

## Resumir y redactar en español con Ollama

Después de incorporar esta función, aplica la configuración de red y código con:

```bash
cd /home/marti/docker/news-radio
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

1. Recarga `http://localhost:8790` (o la IP de este PC con el puerto 8790). En **Mesa de redacción**, pulsa **Comprobar Ollama**. Debe aparecer conectado con tu modelo y «Razonamiento desactivado».
2. Busca una noticia en **Fuentes directas** y pulsa **Redactar en español**. Para Reddit, cambia **Contenido** a Reddit. Los resultados externos de SearXNG todavía no tienen esta acción porque no forman parte de la biblioteca.
3. El panel comienza con el extracto guardado. Pulsa **Descargar texto de la fuente** para intentar aislar el cuerpo de la noticia. En publicaciones sociales utiliza el enlace externo, nunca los comentarios de Reddit. La extracción es heurística y requiere revisión: no garantiza una copia íntegra del artículo. No ejecuta JavaScript, no extrae PDF y no elude bloqueos ni suscripciones. Si falla, lo indica y conserva el extracto; puedes pegar un texto mejor manualmente.
4. Revisa el texto de entrada y pulsa **Generar borrador en español**. La petición usa la [API de chat de Ollama](https://docs.ollama.com/api/chat), `think: false` y `stream: false`; se resume y se redacta directamente en español en una sola llamada. El modelo se utiliza tal como está instalado, sin descargar otros modelos. Solo se permite una generación simultánea para no saturar este PC.
5. A la derecha verás el titular, el guion, las observaciones del modelo y el tiempo de generación. Corrige lo necesario y pulsa **Guardar revisión**. Puedes copiar el texto; en conexiones HTTP por IP, el navegador puede requerir Ctrl+C.
6. Los borradores aparecen en **Instrucciones editoriales y últimos borradores**, y al reabrir la misma noticia. Cerrar el panel no cancela una generación. Reiniciar el servicio sí la interrumpe y deja el intento marcado como error, listo para reintentar manualmente.

### Cambiar el estilo

Edita [`config/editorial.md`](config/editorial.md). Contiene público, tono, extensión, criterios de atribución y reglas de locución. Se relee en cada generación sin reconstruir ni reiniciar Docker. Se limita a 6.000 caracteres; el texto de entrada a 12.000. La interfaz avisa si el material está limitado. Estos topes contienen el coste de inferencia local, no garantizan la calidad editorial.

Cada borrador guarda en `data/news.sqlite3` el texto exacto enviado, su URL, el título, autor y fecha de origen, las instrucciones y su huella SHA-256, el modelo, el resultado y las métricas devueltas por Ollama. La revisión manual se conserva por separado del resultado original. Los cambios posteriores del fichero editorial no alteran los borradores existentes.

Los nuevos guiones terminan automáticamente con «Fuente de esta noticia: …».
El servicio añade esta frase después de la respuesta de Ollama y cierra antes la
última frase si le falta puntuación. Se cita el medio del texto realmente resumido,
no el buscador ni la red social que permitió encontrar un enlace externo. Para un
medio del catálogo se utiliza su nombre; para otros, el dominio de la página.
Si se resume el extracto de una publicación social, se cita su fuente social.
La atribución forma parte del guion que recibe TTS y no añade llamadas a la IA.
Los borradores y audios ya generados conservan su contenido anterior.

Variables opcionales de `.env` (requieren recrear el servicio con `up -d`):

```dotenv
OLLAMA_MODEL=hf.co/lmstudio-community/gemma-4-E2B-it-GGUF:Q4_K_M
OLLAMA_TIMEOUT_SECONDS=300
# Solo si Ollama está en otro equipo o puerto:
# OLLAMA_URL=http://192.168.1.10:11434
```

La descarga de artículos solo se produce al pulsar su botón y se guarda para reutilizarla, incluso si falla. Abrir noticias, consultar borradores o generar de nuevo no repite descargas ni actualiza feeds. No hay comprobación independiente de hechos: la redacción es un borrador para revisión humana. No se genera voz ni se publica nada.

### Compartir este PC con Qwen TTS

El proyecto independiente `/home/marti/docker/qwentts` comparte el bloqueo de inferencia de `../.ai-runtime/inference.lock`. La redacción espera si Qwen está generando; la web y las fuentes siguen funcionando. Ollama utiliza `keep_alive: 0` para liberar el modelo al terminar la respuesta. Qwen confirma que Ollama no mantiene modelos antes de cargar el suyo y libera su proceso al finalizar. La coordinación se aplica a estos dos servicios; una consulta directa a Ollama desde otro programa no participa en el bloqueo. La locución se solicita por ahora desde la web propia de Qwen TTS (puerto 8791).

API editorial: `GET /api/editorial`, `GET /api/editorial/connection`, `GET /api/editorial/article?id=…`, `POST /api/editorial/prepare` y `POST /api/editorial/generate` (con `article_id`, y `text` opcional en generate), `GET /api/editorial/drafts/{id}` y `POST /api/editorial/drafts/{id}/review` (con `title` y `script`).

## Búsqueda complementaria con SearXNG

Selecciona **SearXNG (complementario)** para buscar información fuera de la bandeja. Los resultados de esa búsqueda no se guardan automáticamente ni se mezclan con las noticias recopiladas.

Además hay dos fuentes automáticas con `connector: "searxng"` en
`config/sources.json`: búsqueda de noticias y búsqueda general. Esas fuentes sí
incorporan a la biblioteca los resultados fechados. Sus campos editables son
`queries` (de una a cuatro búsquedas), `category` (`news` o `general`), `time_range`
y `refresh_seconds`. Se consultan cada hora, junto a los conectores directos.
Para otro tema, cambia también estas consultas.

Cuando falta una fecha, se buscan metadatos de publicación en un máximo de cuatro
páginas por fuente y ciclo. Las extracciones y los errores se cachean durante un
día en `data/search-pages.sqlite3`. La redacción reutiliza el texto extraído; no
vuelve a descargarlo. Los resultados sin fecha fiable o fuera de la ventana no se
presentan como recientes. El lector sigue sin descargar hilos de Reddit.

Si una búsqueda con filtro temporal no devuelve resultados y sus motores notifican errores, se intenta una sola vez sin ese filtro. La interfaz identifica expresamente los resultados como **sin filtro temporal**; una fecha ausente aparece como **Fecha sin verificar**. No se garantiza que esos artículos pertenezcan al periodo solicitado.

`SEARXNG_GENERAL_ENGINES` y `SEARXNG_NEWS_ENGINES` permiten seleccionar motores por consulta sin cambiar la instancia. Vacíos usan la selección de la instancia. Si la búsqueda general no devuelve resultados, `SEARXNG_FALLBACK_ENGINES` permite una selección de respaldo (por defecto `bing`, sin filtro temporal porque ese motor no lo admite aquí). Dejar esta última variable vacía desactiva el respaldo. Los resultados automáticos siguen necesitando una fecha comprobable dentro de la ventana. Si fallan los motores, se registra la incidencia y continúan funcionando RSS, Reddit, Mastodon y Bluesky.

La URL base de SearXNG se configura con `SEARXNG_URL` en `.env`; el valor inicial para la instalación de Community Scripts es `http://192.168.1.9:8888`. La instancia debe permitir acceso desde el contenedor y tener habilitada la salida `json` de la API. SearXNG documenta la consulta `GET /search` con `format=json`; algunas instalaciones de Community Scripts no habilitan ese formato por defecto. Si está deshabilitado, el buscador mostrará un mensaje indicando el ajuste necesario.

Si la búsqueda devuelve un error 403 por el formato JSON, entra en el contenedor LXC de SearXNG y edita `/etc/searxng/settings.yml`. Dentro de la sección `search:` añade `json` a la lista existente `formats:` (sin duplicar `search:`), por ejemplo:

```yaml
search:
  formats:
    - html
    - json
```

Después aplica el cambio con `systemctl restart searxng`. La plantilla de Community Scripts indica que SearXNG escucha en el puerto 8888.

Para construir la imagen de despliegue:

```bash
docker compose -f compose.yaml build
```

## Próximo paso funcional

Revisar la utilidad de esta bandeja y la fidelidad de los primeros borradores, afinar las instrucciones editoriales y decidir qué noticias seleccionar. Después se podrá añadir agrupación por acontecimiento y generación de voz a partir de textos revisados.

## Fuentes sin RSS y revisión del catálogo

La revisión del 18/10/2026 se documenta en [docs/SOURCE_REVIEW.md](docs/SOURCE_REVIEW.md).
Anthropic utiliza `connector: "newsroom"`: lee las tarjetas fechadas de su página
oficial cada hora, con `article_path: "/news/"`. La recogida descarga una página;
el cuerpo de cada noticia se obtiene solo al seleccionarla para redacción.
No ejecuta JavaScript ni necesita un servicio externo de conversión a RSS.
Si cambia la estructura y dejan de reconocerse títulos y fechas, la fuente pasa
a error. No se sustituyen las fechas de publicación por la hora de descarga.

AP y Reuters están desactivadas por respuestas HTTP de rechazo desde este equipo.
NVIDIA IA, Microsoft Research y TechCrunch IA aportan RSS adicionales comprobados.
El catálogo sigue siendo editable en `config/sources.json`; los intervalos mínimos
de consulta se respetan también al solicitar una actualización manual.

## Organización


- `catalog.py`: lectura y validación de las fuentes configuradas.
- `feeds.py`: descarga directa y normalización de RSS/Atom.
- `connectors.py`: adaptación de RSS y API pública de Bluesky, con filtros de vocabulario.
- `library.py`: biblioteca SQLite, procedencia, fechas y filtros.
- `collector.py`: recopilación periódica y estado de las fuentes.
- `search.py`: adaptador opcional de SearXNG.
- `article_text.py`: extracción manual y acotada del texto de una fuente pública.
- `ollama.py`: cliente de redacción local, sin razonamiento.
- `editorial.py` y `editorial_store.py`: flujo de redacción, copias del material y borradores persistentes.
- `__main__.py` y `web/`: API y panel de revisión.

Solo debe ejecutarse una instancia del servicio mientras el colector forme parte del mismo proceso. Si hace falta escalar, se extraerá a un trabajador independiente.
