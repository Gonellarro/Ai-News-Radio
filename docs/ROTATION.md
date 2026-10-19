# Renovación de la parrilla

En `config/channel.json`:

```json
"scan_interval_seconds": 3600,
"new_stories_per_hour": 5,
"max_playlist": 20,
"max_pending": 10
```

Son cuatro conceptos independientes: buscar una vez por hora, incorporar hasta
cinco noticias nuevas cada 60 minutos, mantener veinte terminadas en parrilla y
seleccionar hasta diez pendientes. Revisar noticias manualmente adelanta la
búsqueda, pero no salta el límite de producción.

## Cadencia y contador

`new_stories_per_hour` admite enteros positivos y se relee automáticamente. Con
cinco, los inicios de producción se separan aproximadamente doce minutos. El
intervalo incluye el tiempo empleado en preparar la noticia: si producirla tarda
diez minutos, quedan unos dos minutos hasta el siguiente inicio. Con Piper, si
termina antes, descansa el resto del intervalo. Si tarda más, no añade doce
minutos extra después de terminar.

El contador utiliza `source_publications.recorded_at`, el historial persistente
de incorporaciones reales a la parrilla. La ventana es móvil de sesenta minutos,
no se reinicia al cambiar de hora ni al reiniciar Docker. Se comprueba de nuevo
al reclamar cada trabajo, dentro de la transacción de SQLite. No se acumulan
cupos de horas inactivas para generar después una ráfaga.

Los fallos, artículos omitidos, vídeos no admitidos y cambios de presentación no
consumen cupo. La cadencia de la última noticia incorporada usa el inicio que se
guarda en `work.production_started_at`; para noticias anteriores a esta versión
se utiliza su fecha de incorporación. El módulo puro `rotation.py` calcula las
esperas y permanece separado de las políticas de fuentes de `balancing.py`.

En la web, **Producción automática** muestra incorporaciones de los últimos
sesenta minutos y el próximo inicio permitido durante una pausa. La búsqueda y
la emisión continúan durante esa pausa. Un cambio de configuración no interrumpe
una locución ya iniciada; reducir el límite puede dejar temporalmente el contador
por encima del nuevo valor hasta que expiren las incorporaciones anteriores.

Cinco es el objetivo y el límite, no una garantía de capacidad. Hacen falta
candidatas que cumplan la selección y tiempo suficiente para redactar, sintetizar
y generar vídeo. Qwen mantiene su coste y sus posibles fallos de locución. El
llenado inicial también respeta este límite y nunca se aumenta el paralelismo.

## Corrección de la comprobación de fechas

La extracción puede encontrar una fecha original anterior a la indicada por el
feed o por una publicación social. Antes de decidir si merece redactarse, esa
fecha se actualiza ahora tanto en `job.published_at` en memoria como en el artículo
y en SQLite. Así la admisión previa y la selección final ordenan con la misma
fecha. Se conserva `article.discovery_published_at` como procedencia.

Los trabajos parcialmente preparados también se revisan antes de dedicar más
recursos, y se repite la admisión antes de enviar una nueva solicitud de voz.
Una solicitud Qwen ya enviada conserva su identificador y se deja terminar. Los
vídeos que fueron rechazados anteriormente no se vuelven a generar.
