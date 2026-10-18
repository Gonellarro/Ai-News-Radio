# Revisión de fuentes — 18/10/2026

## Fuentes que estaban incompletas

| Fuente | Comprobación desde el equipo | Resultado |
| --- | --- | --- |
| Anthropic | Newsroom HTTP 200; `/news/rss.xml` HTTP 404 | Activada mediante lectura directa de las tarjetas con título, enlace y fecha. |
| Associated Press | Sección de IA, `/technology.rss` y un artículo devuelven HTTP 403 | Desactivada; no se presenta como conectada. |
| Reuters | Sección de IA y un artículo devuelven HTTP 401 | Desactivada; no se presenta como conectada. |

La página de Anthropic descargada permitió reconocer diez noticias, tres de ellas
dentro de los siete días anteriores a la revisión. No se depende de feeds
republicados por terceros. Se conservan las fechas que publica Anthropic; cuando
solo hay día, se representa a medianoche UTC, sin inventar una hora precisa.

También se consultó SearXNG una vez por cada medio bloqueado. Encontró enlaces de
AP y Reuters, pero sin fechas utilizables en esos resultados. La extracción de
los artículos seguía bloqueada. Por eso no se configuraron esas búsquedas como
sustitutos de un feed que funcione. Las búsquedas generales existentes continúan
pudiendo descubrir enlaces de esos medios según lo que devuelvan sus motores.

## RSS añadidos para ampliar el material disponible

| Fuente | RSS comprobado | Entradas descargadas antes del filtro |
| --- | --- | --- |
| NVIDIA IA | https://blogs.nvidia.com/blog/category/generative-ai/feed/ | 18 |
| Microsoft Research | https://www.microsoft.com/en-us/research/feed/ | 10 |
| TechCrunch IA | https://techcrunch.com/category/artificial-intelligence/feed/ | 20 |

Microsoft Research se filtra por vocabulario de IA. NVIDIA y Microsoft son fuentes
de anuncios e investigación propios; TechCrunch es un medio periodístico. Las
tres fuentes se consultan como máximo una vez por hora y los identificadores
existentes mantienen la deduplicación habitual.

## Límites

Esta revisión amplía la recogida; no cambia la selección de trabajos ni introduce
cuotas por plataforma. La producción mantiene su límite de trabajos pendientes y
solo redacta y sintetiza las noticias seleccionadas. La reserva de candidatos no
se envía masivamente a Ollama o Qwen.

Para reactivar AP o Reuters debe configurarse primero una vía utilizable y volver
a comprobar que aporta enlaces y fechas, además del texto necesario para redactar.
Cambiar únicamente `enabled` no completa un conector inexistente.
