# Configuración

## Dos niveles

`.env` configura Docker: puertos publicados, perfiles, imágenes, rutas y límites.
Se relee al recrear los contenedores con `start.sh` o `docker compose up -d`.

Los JSON del canal y del catálogo son datos de la aplicación. Se crean una sola
vez desde `config/examples/` y después se gestionan desde el dashboard o editando
los archivos de `state/`. Reiniciar o reconstruir no borra esos ajustes.

| Archivo/directorio | Contenido |
| --- | --- |
| `state/orchestrator/config/channel.json` | Horario, tamaño del lote, parrilla, voz, balance e IA editorial |
| `state/news-radio/config/sources.json` | Fuentes autorizadas, conectores y frecuencias |
| `state/orchestrator/config/editorial.md` | Instrucciones editoriales para los trabajos automáticos |
| `state/news-radio/config/editorial.md` | Instrucciones de la redacción manual del colector |
| `state/orchestrator/config/visuals.json` | Colores y diseños de tarjetas |
| `state/orchestrator/data/intros/` | MP3 propios para intros aleatorias |
| `state/orchestrator/data/branding/logos/` | Logotipos opcionales |
| `state/qwentts/voices/` | Referencias de voz y biblioteca importada |

Si cambias `STATE_DIR`, estas rutas son relativas a ese directorio.

`TTS_ENGINE`, `INITIAL_AUTOMATION_ENABLED`, `CHANNEL_NAME`, `CHANNEL_TOPIC` y
`SCHEDULE_TIMEZONE` solo inicializan un canal nuevo. Para un canal existente usa
Panel de control; editar esos valores de `.env` no reemplaza un JSON existente.

## Horario y renovación

`scan_interval_seconds` admite 1800, 3600, 21600 o 43200. El calendario usa medias
horas y horas en punto de `schedule_timezone`, inicialmente Europe/Madrid.
`new_stories_per_update` es el objetivo de incorporaciones de cada lote.
`max_playlist` limita vídeos terminados y `max_pending` los trabajos seleccionados,
contando el que está en producción. La reserva no se convierte entera en audio.

Cada incorporación retira la entrada más antigua sin fijar; la fecha original de
la noticia y su puntuación no la protegen de esa renovación. Reordenar no rejuvenece
una entrada. Si toda la parrilla está fijada, no hay espacio para renovación.

## Fuentes

Incluye las fuentes públicas del proyecto original. Las desactivadas o sin vía
validada conservan sus notas. Los perfiles públicos son ejemplos editables.
La interfaz de Búsqueda y fuentes administra el catálogo; no hace falta tocar código.

SearXNG está desactivado en los ejemplos. Para usar uno propio, configura
`SEARXNG_URL=https://tu-instancia.example`, recrea `news-radio` y activa sus fuentes
en el catálogo. La búsqueda manual también lo utiliza. Los feeds siguen funcionando
si SearXNG no está disponible. Los límites de Reddit se conservan en disco: repetir
búsquedas y reiniciar no elimina sus pausas.

## Voz, intros y logotipos

Piper usa Davefx en español. Qwen requiere su perfil, modelo descargado y al menos
una voz activa en la biblioteca. En otro puerto, ajusta también `QWENTTS_PUBLIC_URL`
para que el enlace del navegador apunte a la dirección publicada. `localhost` se
adapta al nombre del equipo usado al abrir el dashboard.

Las intros están desactivadas inicialmente. Añade tus MP3 y actívalas desde el panel.
Los logos no se redistribuyen como binarios. Puedes descargarlos explícitamente:

```bash
python3 scripts/manage.py logos
```

La importación informa de los recursos que no consigue descargar. Sin logo, la
tarjeta sigue mostrando texto y color de la fuente. Las noticias citan su fuente
al final de la locución, incluso cuando se escuchan sin imagen.
