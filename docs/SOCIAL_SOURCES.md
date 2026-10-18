# Redes y comunidades

Las publicaciones sociales amplían el descubrimiento. Se guardan como señales por contrastar, con su enlace original, autor cuando la fuente lo proporciona, fecha de publicación y un enlace compartido si está disponible. Ese enlace no se confunde con el de la publicación ni implica verificación.

## Selección inicial

| Red | Cuenta o flujo | Qué buscamos |
| --- | --- | --- |
| Reddit | LocalLLaMA | Modelos locales y abiertos, lanzamientos y pruebas de inferencia. |
| Reddit | MachineLearning | Entradas con etiquetas textuales `[R]`, `[N]`, `[Research]` o `[News]`. |
| Reddit | LanguageTechnology | NLP, artículos, conjuntos de datos y modelos. |
| Reddit | artificial | Actualidad de IA filtrada por vocabulario de investigación y lanzamientos. |
| Mastodon | Simon Willison | Herramientas, agentes y uso práctico de LLM. |
| Mastodon | Armin Ronacher | Experiencias de ingeniería con herramientas y agentes. |
| Mastodon | Timnit Gebru | Evaluación crítica e impacto social de la IA. |
| Mastodon | #LLM, en sigmoid.social | Modelos de lenguaje y herramientas. |
| Mastodon | #MachineLearning, en sigmoid.social | Investigación y proyectos. |
| Bluesky | Simon Willison | LLM y herramientas. |
| Bluesky | Melanie Mitchell | Inteligencia, razonamiento y evaluación. |
| Bluesky | Ethan Mollick | Aplicaciones y comentarios sobre estudios de IA. |
| Bluesky | Machine Learning, de arinbjorn.is | Feed técnico de investigación e implementación. |
| Bluesky | Papers with Code, de Stephen Turner | Enlaces a artículos y código, filtrados por vocabulario de IA. No es la antigua web Papers with Code. |

Los identificadores y enlaces concretos están en `config/sources.json`. La selección es editable. Se descartaron otras cuentas cuyos feeds consultados estaban inactivos o devolvían errores; no se añadieron solo por su notoriedad.

## Cómo consultarlas

En **Fuentes directas → Contenido**, selecciona **Redes y comunidades**, una red concreta o **Todas las publicaciones**. La vista inicial muestra **Medios y fuentes oficiales**. El selector de fuente se adapta al contenido elegido.

Los filtros de fecha se aplican a la publicación social, no al artículo que esta enlaza. Los posts sin fecha se excluyen de periodos limitados. Las redes no traducen los textos: `language` describe el idioma habitual de la fuente; los flujos multilingües (`mul`) aparecen al seleccionar **Todos**.

## Catálogo y conectores

- `platform`: `web`, `reddit`, `mastodon` o `bluesky`. Si falta, se interpreta como `web`.
- `connector: rss`: lee `feed_url`, válido para RSS y Atom. Reddit y Mastodon usan esta vía pública.
- `connector: bluesky_author`: consulta el feed público de `actor`, sin credenciales.
- `connector: bluesky_feed`: consulta un feed temático público identificado por `feed`, una URI `at://did:.../app.bsky.feed.generator/...`.
- `keywords`: lista opcional; basta con encontrar una palabra o frase completa en el título o extracto, sin distinguir mayúsculas ni acentos. Lista vacía = sin filtro. No es una clasificación semántica y puede dejar pasar ruido o excluir contenido útil.
- `require_link: true`: exige un enlace compartido; se activa para los cuatro flujos de Reddit para reducir consultas sin referencias. Estos filtros se aplican también a las publicaciones ya guardadas.
- `enabled: false`: desactiva la consulta y oculta las entradas de esa fuente, conservando el historial.

Los autores de Bluesky excluyen respuestas y republicaciones para reducir duplicados y mensajes sin contexto. Los feeds temáticos son mantenidos por terceros: no garantizan cobertura completa. Los feeds de etiquetas de Mastodon solo reflejan lo que conoce el servidor elegido; no recorren toda la red.

Las cuentas personales pueden publicar asuntos ajenos a IA. Por ello se aplica el filtro de vocabulario configurado a las seleccionadas. Los resultados de ese filtro se revisarán con el uso real.

## Acceso y límites

La integración usa RSS/Atom públicos y la AppView pública de Bluesky. No requiere claves ni activa servicios de pago. No utiliza la búsqueda global de Bluesky: el endpoint consultado rechazó el acceso anónimo; se emplean feeds públicos concretos que sí respondieron.

El acceso a Reddit ha sido irregular: los flujos han alternado respuestas válidas con HTTP 429 desde esta red. Su estado real se muestra en el panel y puede cambiar. Se usa esta política conservadora:

- Cada flujo de Reddit se revisa como mínimo cada dos horas.
- Se permite una sola petición a Reddit en cada turno de 30 minutos, rotando entre flujos. Se registra el turno antes de la petición.
- Un HTTP 429 pausa Reddit completo durante al menos seis horas. Si se repite, la pausa sube a doce y después a veinticuatro horas. Un `Retry-After` más largo siempre se respeta.
- La pausa y el presupuesto de peticiones se guardan en SQLite y sobreviven a los reinicios. Los errores 429 ya registrados se incorporan a esa pausa antes de plantear nuevas peticiones.
- El botón de actualización no fuerza peticiones antes de plazo. Tampoco se repiten consultas recientes a las demás fuentes al reiniciar.
- Buscar y filtrar entradas usa solo la biblioteca local; no consulta Reddit. No se sustituyen dominios ni se intentan eludir restricciones.

Los valores se configuran con `NEWS_RADIO_REDDIT_INTERVAL_SECONDS=7200`, `NEWS_RADIO_REDDIT_REQUEST_GAP_SECONDS=1800` y `NEWS_RADIO_REDDIT_COOLDOWN_SECONDS=21600`. El campo opcional `refresh_seconds` de una fuente puede alargar su intervalo. La revisión general del colector continúa cada 30 minutos y consulta únicamente las fuentes que ya deban actualizarse.

Las noticias ya recogidas siguen disponibles aunque una plataforma falle. No se generan guiones ni se publican automáticamente estos posts.

Referencias: [API pública de Bluesky](https://docs.bsky.app/docs/api/app-bsky-feed-get-author-feed), [feeds de Mastodon](https://docs.joinmastodon.org/user/network/), [perfil Mastodon de Simon enlazado desde su web](https://simonwillison.net/2022/nov/5/mastodon/).
