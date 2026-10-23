# Actualizaciones por calendario y producción por lotes

Configuración en `config/channel.json`:

```json
{
  "scan_interval_seconds": 3600,
  "schedule_timezone": "Europe/Madrid",
  "new_stories_per_update": 5,
  "max_playlist": 20,
  "max_pending": 10
}
```

## Horarios discretos

| Frecuencia | Segundos | Horarios locales |
| --- | --- | --- |
| 12 horas | 43200 | 00:00 y 12:00 |
| 6 horas | 21600 | 00:00, 06:00, 12:00 y 18:00 |
| 1 hora | 3600 | Cada hora en punto |
| Media hora | 1800 | Cada hora en punto y a y media |

Se elige en **Panel de control → Canal y automatización → Horario de actualización**.
La API y el fichero rechazan otros intervalos. `schedule_timezone` se puede editar
en la configuración completa; por defecto se utiliza Madrid. Los plazos se guardan
en UTC y se calculan con las reglas de la zona, incluidos cambios de hora. En otoño
se admiten las dos apariciones de una hora repetida; las horas inexistentes de
primavera se omiten. El bucle comprueba el reloj cada dos segundos: el disparo puede
tener ese pequeño retraso de planificación, sin desplazar la siguiente franja.

La próxima revisión se calcula desde el reloj, no desde el final de la anterior.
Cambiar frecuencia o zona y reanudar la automatización programa la siguiente franja
futura; no provoca una búsqueda inmediata. Reiniciar tampoco acumula revisiones
perdidas. Un lote que ya había comenzado sí puede continuar tras el reinicio.

**Revisar noticias ahora** abre un lote manual inmediato, incluso con la automatización
pausada, y mantiene la próxima revisión automática. Las fuentes conservan sus límites,
cachés y periodos de espera. Al arrancar o rellenar la reserva se puede consultar la
biblioteca local, sin forzar lecturas remotas ni abrir un lote fuera de hora.

## Flujo de cada actualización

1. Abre un lote con el tamaño configurado y refresca las fuentes disponibles.
2. Actualiza candidatas y aplica la selección y el balance de fuentes. La valoración
   editorial opcional conserva sus modos y presupuesto; sus pasadas automáticas se
   limitan a lotes activos. Las peticiones humanas siguen teniendo prioridad.
3. Produce las seleccionadas de una en una: extracción, resumen/traducción, locución,
   normalización, vídeo e incorporación a parrilla. Al acabar una empieza la siguiente.
   Cada vídeo nuevo sustituye a la noticia que lleve más tiempo en parrilla, excepto
   las fijadas. El balance y la IA eligen candidatas; no protegen noticias antiguas
   frente a esta renovación. Solo se retira una pieza cuando su sustituta está lista.
4. Al alcanzar el número de incorporaciones del lote, espera a la próxima revisión.
   Si faltan candidatas elegibles, cierra el lote sin gastar recursos en un bucle vacío.
   Los reintentos pendientes conservan su espera y su límite de intentos.

`new_stories_per_update` es el objetivo y máximo de incorporaciones **por actualización**.
Con 5 y una hora se producen cinco seguidas por hora; con media hora se pueden producir
hasta diez por hora. Con seis o doce horas se producen cinco por actualización, sin
multiplicar el lote por las horas transcurridas. El valor se captura al abrir el lote;
cambiarlo afecta a las actualizaciones siguientes. El parámetro antiguo
`new_stories_per_hour` se migra a este nuevo nombre conservando su valor.

La capacidad de parrilla y los trabajos pendientes son límites independientes. Solo
las candidatas seleccionadas para producción reciben resumen, traducción y voz; la
reserva completa no se transforma en audio. Si llega otra actualización antes de que
termine el lote, se sustituye el trabajo todavía no iniciado por el lote más reciente.
La noticia en marcha termina su proceso completo y queda contabilizada en su lote
original. No se acumula una cola ilimitada de actualizaciones atrasadas ni se aumenta
el paralelismo. La velocidad de Qwen/Piper determina la capacidad real de producción.

Los contadores del lote y sus incorporaciones se guardan en SQLite, en
`production_cycles` y `cycle_publications`. Reiniciar no reinicia el cupo de un lote.
Solo cuentan vídeos admitidos; los fallos y las repeticiones de emisión no consumen
cupo. El total de publicaciones de los últimos sesenta minutos sigue disponible como
dato informativo. La emisión local y YouTube reproducen la parrilla durante las pausas.

## Organización

- `scheduling.py`: franjas de calendario, zona horaria y opciones del selector.
- `rotation.py`: cálculo puro del permiso de producción del lote.
- `playlist_rotation.py`: admisión por capacidad y renovación por tiempo en parrilla.
- `store.py`: persistencia, transacciones, reclamación y contabilización por lote.
- `pipeline.py`: recopilación programada y ejecución serial de las noticias.

## Fecha del material

La extracción puede encontrar una fecha original anterior a la del feed o publicación
social. Se actualiza tanto en memoria como en SQLite antes de decidir la admisión,
conservando `article.discovery_published_at` como procedencia. Los trabajos preparados
se revisan antes de invertir más recursos; una solicitud Qwen ya enviada conserva su
identificador y se deja terminar. Los vídeos rechazados no se vuelven a generar.
