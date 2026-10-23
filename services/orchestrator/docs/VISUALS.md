# Tarjetas estáticas y logotipos

Cada noticia tiene un PNG de 1280×720 que se prepara una vez con Pillow y se usa
como imagen fija de su MP4. La emisión sigue copiando los segmentos ya preparados.
No se genera imagen con IA ni se descargan recursos durante la producción habitual.

## Archivos

- `config/visuals.json`: fuentes, dominios, color, nombre de PNG, composiciones,
  familias tipográficas y temas permitidos.
- `data/branding/logos/`: PNG locales y metadatos de procedencia de cada recurso.
- `data/branding/originals/`: originales descargados antes de su conversión.
- `config/logo_sources.json`: direcciones de importación y páginas originales.
- `data/media/<id>/poster.png`: tarjeta final utilizada en el vídeo.
- `data/media/<id>/visual.json`: diseño elegido, fuente, tipografía, tamaño, número
  de líneas, colores y contraste calculado de cada texto.
- `presentation.json`: identidad completa de la presentación, incluido el diseño.

La galería de fuentes está en `/branding.html`. La parrilla muestra miniaturas y
un enlace **Ver tarjeta** de cada pieza que ya tiene su presentación actualizada.

## Diseño y legibilidad

Hay tres composiciones: logo en esquina, columna lateral o cabecera. El identificador
de la noticia decide de forma reproducible composición, tema claro/oscuro y titular
en DejaVu Sans Bold o DejaVu Serif Bold. El texto auxiliar utiliza Sans y Mono.
No cambia de diseño al reiniciar o reintentar. Si se modifica el catálogo visual,
se aplica la nueva definición a las noticias activas.

El color de cada marca produce un fondo matizado y detalles decorativos. Todos los
textos se dibujan con fondo transparente directamente sobre ese diseño, sin
rectángulos de relleno. El generador ajusta el color del titular, la fuente y los
metadatos hasta alcanzar una relación de contraste mínima de 4,5:1 contra todos
los colores del fondo, incluidos los detalles decorativos, usando luminancia
relativa sRGB.

El titular se distribuye midiendo los píxeles de la tipografía y ajustando su tamaño
entre 30 y 64 px. Si un titular excepcionalmente largo no cabe, se conserva una
versión con puntos suspensivos; el informe `visual.json` lo indica. El logo se escala
con sus proporciones y colores originales sobre una placa blanca con margen. Los
logos ausentes o ilegibles se sustituyen por el nombre de la fuente, sin inventar
un logotipo. Se limita el aumento de iconos pequeños para evitar borrosidad.

La fecha se presenta en `Europe/Madrid`, incluyendo el cambio estacional de hora.

## Identificar la fuente

Se utiliza el dominio del artículo realmente leído, guardado en `source_url`.
Un artículo externo descubierto en Mastodon, Reddit, Bluesky o SearXNG conserva la
identidad del medio original y una referencia a su vía de descubrimiento. Para una
publicación original en una red se utiliza la identidad de esa plataforma.

Un dominio desconocido obtiene un color estable derivado de su nombre y una
identificación textual. Para añadir su logo, agrega la entrada correspondiente al
catálogo y copia un PNG local. No hace falta programar ni reiniciar Docker.

## Añadir o cambiar una fuente visual

Ejemplo de entrada en el objeto `brands` de `config/visuals.json`:

```json
"mi-medio": {
  "name": "Mi medio",
  "accent": "#3979CA",
  "logo": "mi-medio.png",
  "domains": ["mi-medio.example"]
}
```

Copia el archivo a `data/branding/logos/mi-medio.png`. Se admiten PNG de hasta 4 MiB
y 4096×4096 píxeles. Para reemplazar un logo basta sustituir ese PNG: su huella
detecta el cambio y actualiza las tarjetas activas automáticamente. El mantenimiento
prepara una pieza cada vez y conserva los segmentos de la versión anterior hasta
que la emisión ya no los necesita.

Si solo cambia el diseño, el MP3 permanece intacto y el audio AAC del MP4 existente
se copia al vídeo nuevo. No se vuelve a llamar a Ollama o Qwen, ni se repite la
normalización. Si cambian también pausas o volumen, se usa el montaje de audio
habitual desde el WAV original.

## Importar recursos de Internet de forma explícita

Las direcciones y su página de procedencia se guardan en `config/logo_sources.json`.
La importación es una herramienta de administración, no un paso de cada noticia:

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps orchestrator \
  python -m news_orchestrator.logo_assets
```

Conserva archivos existentes. Para actualizar uno:

```bash
docker compose -f compose.yaml -f compose.dev.yaml run --rm --no-deps orchestrator \
  python -m news_orchestrator.logo_assets --force --only mastodon
```

Descarga hasta tres recursos a la vez y limita tamaño y tiempo. Los SVG se convierten
a PNG con librsvg/FFmpeg; se rechazan scripts y referencias externas. Los metadatos
incluyen URL, página original, fecha, dimensiones y huellas. Los recursos siguen
perteneciendo a sus respectivas fuentes.

Las tarjetas se eliminan con la noticia al retirarse de la parrilla. Los originales
y la biblioteca común de logos se conservan para reutilizarlos.
