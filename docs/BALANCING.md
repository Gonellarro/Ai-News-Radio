# Balanceo de fuentes

## Comportamiento de `fair`

1. Cuenta las noticias distintas que cada fuente ha incorporado a la parrilla.
2. Elige primero entre las fuentes con menor contador, dividido por su peso.
3. Reserva también el turno del trabajo en curso y los turnos ya seleccionados
   para la cola, para no llenar todas las plazas con una misma fuente.
4. Dentro de cada fuente utiliza primero las noticias más recientes de la ventana
   `max_age_hours`. Los empates entre fuentes favorecen a la menos presente en la
   parrilla y después a la noticia más reciente.
5. Solo participan fuentes con candidatas utilizables. Una fuente vacía, bloqueada
   o sin material elegible no paraliza la producción: se utilizan las demás.

La compensación es progresiva. Una fuente nueva empieza en cero y gana prioridad
frente a otras que ya han publicado mucho. No se generan noticias inexistentes
para igualar contadores ni se exige igualdad cuando falta material en una fuente.

Los trabajos que ya tienen redacción o voz iniciadas continúan antes que los nuevos,
respetando el horario de sus reintentos. Esto evita desperdiciar inferencias o
abandonar un audio remoto al cambiar la política o reiniciar. Los fallos mantienen
el límite de tres reintentos y no aumentan el contador de publicaciones.

## Fuente y contador

Una fuente es el `source_id` del catálogo de News Radio: por ejemplo `xataka-ai`,
`anthropic-news` o `mastodon-llm`. No equivale a toda una plataforma. Las dos
etiquetas de Mastodon llevan contadores separados, igual que los distintos medios
y cuentas. Una noticia duplicada encontrada en varias fuentes solo se produce una
vez y se atribuye para el reparto a la fuente guardada en su trabajo. La atribución
oral y visual sigue identificando por separado al editor del texto realmente leído.

La tabla SQLite `source_publications` registra una fila por noticia incorporada,
con `job_id` único, fuente, nombre, plataforma y fecha de registro. El contador
es la suma de sus filas por fuente. Se actualiza dentro de la misma transacción
que cambia la parrilla y no disminuye al retirar o borrar un MP3/MP4. Las vueltas
del bucle, actualizaciones gráficas y reinicios no vuelven a contar una noticia.

Al desplegar por primera vez, se reconstruye el historial de los trabajos `ready`,
incluidos los retirados cuyos archivos ya se borraron. Una marca persistente evita
repetir la migración. Para esos registros históricos se conserva `updated_at` como
fecha aproximada de registro; sus contadores sí corresponden al historial guardado.

En la web del orquestador, **Balance de fuentes → Ver contadores por fuente** muestra
publicaciones históricas, noticias en parrilla, trabajos pendientes, reserva y peso.
También se expone en `GET /api/status`, campo `source_balance`.

## Parrilla y caducidad

La parrilla utiliza plazas flexibles: reparte una por fuente disponible antes de
dar plazas adicionales, según los pesos. Cuando faltan piezas en una fuente, otras
ocupan los huecos. Conserva primero las noticias más recientes de cada fuente y
usa el historial como desempate entre fuentes. Una fuente nueva puede desplazar
una pieza de una fuente sobrerrepresentada aunque su noticia sea algo anterior.

Antes de gastar recursos en una candidata se comprueba si podría entrar. Se vuelve
a comprobar cuando la extracción aporta la fecha real del artículo. Los candidatos
sin hueco permanecen en reserva hasta caducar; no se redactan ni sintetizan por
estar en esa reserva. Las piezas terminadas se mantienen hasta tener sustitutos.
Si solo hay una fuente utilizable, puede ocupar toda la parrilla y toda la cola.

La migración puede recuperar candidatos que la regla anterior excluyó solo por
ser más antiguos que el corte global: únicamente si siguen apareciendo en la
biblioteca consultada, nunca se iniciaron (`work = {}`), no tuvieron fallos y no
guardan resultado ni error. La operación comparte el bloqueo con la limpieza.
Los vídeos retirados y las noticias descartadas o ya procesadas no se reactivan.

`max_playlist` y `max_pending` conservan sus funciones. El segundo incluye el trabajo
en curso; los reintentos aplazados conservan sus horarios por separado. La producción
sigue siendo secuencial y solo las plazas seleccionadas llegan a Ollama y Qwen.

## Configuración

En `config/channel.json`, sin necesidad de reiniciar:

```json
"balancing": {
  "strategy": "fair",
  "weights": {}
}
```

Con pesos vacíos cada fuente pesa 1. Ejemplo de preferencias relativas:

```json
"balancing": {
  "strategy": "fair",
  "weights": {
    "anthropic-news": 2,
    "mastodon-llm": 0.5
  }
}
```

Los pesos no garantizan cuotas exactas cuando falta material. Se admiten valores
positivos de 0,01 a 100. Para volver a la selección global por fecha, usa
`"strategy": "latest"`; el historial se sigue guardando y queda disponible al
reactivar `fair`.

## Cambiar el algoritmo

`balancing.py` contiene las políticas puras y el registro `POLICIES`. Una nueva
implementación proporciona:

- `queue(candidates, published, running, active, limit, options)`: devuelve trabajos
  en orden de producción, hasta `limit`, considerando los turnos ya ocupados.
- `playlist(jobs, published, limit, options)`: devuelve las piezas que conservar,
  hasta `limit`.
- `description`: texto que identifica la política en la web.

Las funciones comunes `select`, `admits` y `keep` mantienen un contrato estable.
La persistencia y las transacciones pertenecen a `store.py`; la producción utiliza
ese contrato sin conocer la fórmula de puntuación. Cambiar el algoritmo no requiere
modificar Ollama, TTS, el renderizador, la limpieza ni el emisor. Al añadir una clave
al registro, actualiza el texto del error de validación si procede.
