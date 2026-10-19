# Continuidad del audio en YouTube

Los MP4 se codifican por separado y empiezan sus marcas de tiempo desde cero.
HLS anuncia cada cambio mediante `EXT-X-DISCONTINUITY`. La reproducción local
puede manejar esos reinicios, pero el contenedor FLV de RTMP necesita una salida
continua. Copiar los paquetes AAC originales dejaba pequeños solapamientos entre
noticias que FFmpeg notificaba como `Non-monotonic DTS`.

## Salida

`youtube_media.py` mantiene `-c:v copy` y utiliza:

```text
aresample=48000:async=1:first_pts=0:min_hard_comp=0.020,asetpts=N/SR/TB
-c:a aac -b:a 128k -ar 48000 -ac 2 -threads:a 1
```

FFmpeg corrige el desplazamiento del reloj de entrada HLS. El filtro rellena los
huecos y recorta solapamientos; `async=1` no aplica estiramiento de la voz. Tras
esa corrección, los tiempos de salida se calculan contando muestras de audio.
La salida es AAC-LC estéreo a 48 kHz. El vídeo H.264 se conserva sin recodificar.
La biblioteca de voces, la locución original y los MP4 de la parrilla se conservan.

Las discontinuidades de entrada esperadas se cuentan en `input_discontinuities`
y se registran a nivel de depuración, para no presentarlas como averías. Los
retrocesos de salida y otros errores siguen registrándose como advertencias.

## Supervisión

`youtube_health.py` separa el seguimiento de tiempos del supervisor de procesos:

- Sin avance del contenido durante 45 segundos: reconexión.
- Sin avance de bytes enviados durante 45 segundos: reconexión.
- Retroceso del reloj de salida superior a un segundo: reconexión.
- Ritmo inferior a 0,85×, medido sobre al menos treinta segundos y sostenido
  veinte segundos más: reconexión.
- Retraso acumulado superior a veinte segundos durante otros veinte segundos:
  reconexión para acercarse al directo actual.

El retraso se mide desde el primer progreso de cada conexión, con tiempo
monotónico. La latencia interna de YouTube no forma parte de esa medida. La
reconexión tiene esperas progresivas hasta sesenta segundos y no cambia la clave
ni la privacidad del evento. No hay sondeos adicionales a noticias ni modelos.

El estado público incorpora `media_rate`, `lag_seconds`, `audio_mode` y el número
de cambios normalizados. Una salida activa no confirma la publicación del evento:
YouTube Studio controla el inicio, finalización y privacidad. Si YouTube ya cerró
un evento, este módulo sin credenciales de API no puede crear otro. Se recomienda
revisar la finalización automática del evento si debe sobrevivir a cortes.

El registro nuevo utiliza hora de Madrid con desplazamiento explícito, por
ejemplo `2026-10-19T10:45:00.000+02:00`, y explica las paradas solicitadas desde el
panel o por la indisponibilidad de la fuente. Los registros antiguos permanecen
en UTC con su formato anterior. Nunca se incluye la clave en las respuestas o
registros.

## Verificaciones repetibles

Pruebas de construcción del comando y del vigilante, sin emitir:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Secuencia local de más de 25 minutos usando los segmentos reales de la parrilla,
con cambios y vueltas completas. No conecta con YouTube ni utiliza su clave:

```bash
docker compose -f compose.yaml -f compose.dev.yaml exec -T youtube \
  python - < scripts/verify_youtube.py
```

Se toman enlaces físicos bajo el bloqueo de archivos para que retirar una noticia
no interrumpa la comprobación. Se comprueban DTS estrictamente crecientes, paso
de audio continuo, duración total y sincronización final de audio/vídeo. El FLV
temporal y los enlaces se eliminan; se conservan el informe JSON y el registro
en `data/diagnostics/youtube-*/`. Estos informes no tienen credenciales.

### Verificación del 19 de octubre de 2026

- Archivo local de 1.529,92 segundos, con 39 cambios: cero DTS repetidos o hacia
  atrás, cero avisos de audio no monotónico. El paso máximo entre paquetes de
  audio fue de 22 ms y la diferencia entre los últimos DTS de audio y vídeo,
  142 ms.
- Nueve pruebas automatizadas del comando y el vigilante, superadas.
- Observación del envío RTMPS real durante tres minutos, además del arranque:
  seis cambios enlazados, sin errores ni reconexiones y con ritmo cercano a 1×.
- Emisor observado con unos 36 MiB de memoria y menos de 0,2 CPU, dentro de su
  límite de 192 MiB y media CPU.

Informes en `data/diagnostics/youtube-20261019T083507Z/`. La observación real
comprueba el transporte al servidor de YouTube; no certifica la reproducción de
la página pública ni su visibilidad.
