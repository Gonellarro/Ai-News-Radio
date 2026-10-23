# Relevancia editorial opcional

Módulo independiente para valorar qué noticias aportan información al canal. Usa
el mismo modelo configurado en `news-radio` (actualmente Gemma 4 E2B), sin descargar
otro modelo. No cambia la redacción ni el TTS.

## Uso

Dashboard → **Búsqueda y fuentes → Relevancia IA**:

- **Desactivado** (`off`): no consulta el modelo ni usa sus puntuaciones.
- **Observación** (`observe`): evalúa extractos y muestra puntuaciones y motivos.
  No cambia las decisiones de producción o parrilla. Es el modo inicial instalado.
- **Influir en la selección** (`rank`): utiliza las valoraciones guardadas para
  elegir qué producir. La renovación retira las entradas más antiguas sin fijar,
  independientemente de su puntuación. No reordena la reproducción.

Se guardan los ajustes dentro de `relevance` en `config/channel.json`. Se aplican
sin reiniciar. El tema del canal es `topic`; los criterios se editan con **Criterios
y pesos**. Los pesos de afinidad, impacto, novedad y contenido informativo se
normalizan al calcular la nota final. Cambiar pesos no vuelve a consultar el modelo.
Cambiar criterios, tema o material invalida la valoración correspondiente: la nota
anterior sigue visible como **desactualizada**, sin intervenir en la selección. Se
sustituye cuando se completa una valoración nueva, también si antes hay un error.

Valores iniciales: 20 extractos por hora, revisión cada 3.600 segundos, influencia
editorial del 60 % frente al 40 % de actualidad. El límite horario se aplica solo
a las evaluaciones **automáticas**; se calcula sobre los últimos 60 minutos. Sus
pasadas se ejecutan dentro de lotes de actualización activos, sin despertar la IA
para valorar en las pausas del canal. El presupuesto vuelve a estar disponible
según expiran los intentos anteriores.

### Valorar ahora: petición humana prioritaria

- Captura las noticias de la parrilla y los trabajos programados para producción,
  incluida la noticia en curso. No incorpora las cientos de candidatas de reserva.
- Reutiliza las notas vigentes y valora las pendientes, desactualizadas o fallidas.
- Omite el presupuesto y el retraso de reintento automáticos. Cada noticia recibe
  como máximo un intento de inferencia dentro de esa petición manual. Los intentos
  manuales se registran por separado y no consumen presupuesto automático.
- Si hay una noticia en producción, espera a que termine su proceso **completo**:
  extracción, resumen, generación de voz, normalización, vídeo e incorporación a
  parrilla. No se intercala entre el resumen y el TTS. La operación actual conserva
  sus datos y sus ajustes. Si la producción falla por sí misma, conserva sus puntos
  de recuperación habituales; la petición manual no cancela ni rompe operaciones.
- Al quedar libre el productor, se atiende la valoración manual antes de iniciar
  otra noticia automática. Un bloqueo compartido protege la reserva de ese turno.
- Una inferencia automática que ya está en marcha termina su lote antes de atender
  la petición humana. Los servicios de IA externos comparten su bloqueo habitual.
- La petición y su progreso se guardan en SQLite y sobreviven a reinicios. Pulsar
  repetidamente no duplica peticiones pendientes o activas. Se muestran los estados
  de espera, el progreso y el resultado final; un fallo libera la producción.
- Cambiar el texto de los criterios o el tema durante una petición la cancela al
  terminar el lote actual para no mezclar versiones. Se puede solicitar otra con
  los nuevos criterios. Desactivar el módulo también cancela la petición entre lotes.

No descarga noticias ni fuerza peticiones a los feeds. La emisión local y YouTube
siguen reproduciendo la parrilla mientras termina la noticia o se evalúan extractos.

## Decisiones y límites

- Cada petición envía hasta cuatro titulares y extractos de hasta 900 caracteres;
  con criterios largos se reduce el lote para limitar el contexto.
- No descarga artículos ni resume, traduce o sintetiza todas las candidatas. Solo
  los trabajos elegidos por el selector habitual pasan a redacción y TTS.
- Se alternan pendientes, parrilla y reserva, repartiendo oportunidades entre
  fuentes. No se evalúa de golpe toda la biblioteca.
- Afinidad, impacto, novedad intrínseca e información concreta: enteros 0–100 y
  motivo breve. La novedad no es una comprobación semántica contra todas las otras
  noticias; siguen actuando los mecanismos existentes de duplicados.
- Se basa en extractos, puede equivocarse y no verifica credibilidad ni hechos.
- `think: false`, temperatura cero, salida y contexto limitados, dos hilos de CPU,
  `keep_alive: 0`. Comparte el bloqueo de IA con Ollama editorial y Qwen. Si el
  turno está ocupado, se aplaza sin consumir presupuesto o intentos.
- Los fallos automáticos reales cuentan en el presupuesto; hasta tres intentos
  automáticos por versión de un extracto, separados al menos una hora. Reiniciar no borra el presupuesto.
- Si la IA está apagada, no responde o no hay nota vigente, la producción continúa.
  En modo selección, las noticias sin nota reciben una estimación neutral de 50:
  no quedan bloqueadas por estar pendientes de valoración.

Con `fair`, el balance y los pesos de fuentes siguen asignando turnos; la nota
editorial y la actualidad eligen dentro de cada fuente. Con `latest`, esa combinación
se aplica globalmente. Se conservan las protecciones de noticias fijadas, peticiones
manuales, trabajo ya iniciado, capacidad y ritmo de producción. Los trabajos en
marcha conservan sus ajustes: desactivar se aplica entre lotes, sin abortar una
inferencia ya enviada.

Las valoraciones se consultan al seleccionar pendientes. No deciden qué vídeo
retirar: esa decisión utiliza el tiempo en parrilla y las fijaciones manuales.
Recalcular notas no vacía ni congela la parrilla.

## Organización

- `relevance_policy.py`: validación, firma del material y fórmula de orden; sin E/S.
- `relevance_store.py`: caché en `jobs.relevance`, presupuesto persistente y consulta.
- `relevance.py`: trabajo de fondo, pausas, lotes y tratamiento de fallos.
- `web/modules/relevance.js`: panel de controles, notas y motivos.
- `news-radio/src/news_radio/relevance.py`: adaptador de inferencia y validación de
  respuestas. Endpoint interno `POST /api/editorial/relevance`.

API del dashboard: `GET /api/dashboard/relevance?page=1&limit=6` y
`POST /api/dashboard/relevance/evaluate` con `{}`. La configuración utiliza la API
existente con revisión para evitar sobrescribir cambios de otra pestaña.

Para sustituir el modelo, cambia la configuración de Ollama de `news-radio`.
Las notas existentes conservan el nombre del modelo que las produjo; cambiarlo
no las borra. Para renovar el criterio y las valoraciones, edita los criterios.
Para cambiar el criterio, edita la configuración. Para cambiar la fórmula de
selección, modifica el módulo puro sin tocar TTS, emisión, medios o recopilación.
