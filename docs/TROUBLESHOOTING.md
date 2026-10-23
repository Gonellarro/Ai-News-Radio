# Diagnóstico

## No se generan noticias

Comprueba que la automatización está activada, la siguiente franja y los trabajos
pendientes en el dashboard. Se instala pausada. `Revisar noticias ahora` solicita
un lote; la producción necesita automatización activa y modelos disponibles.

Consulta `docker compose logs --tail 100 orchestrator news-radio`. El healthcheck
del orquestador también comprueba sus cinco trabajadores. Salud HTTP no significa
que un modelo esté descargado o que existan fuentes utilizables.

## Falta el modelo de Ollama

```bash
docker compose exec ollama ollama list
```

Comprueba que el nombre coincide exactamente con `OLLAMA_MODEL`. Repite
`./scripts/install.sh` para preparar los pesos. No se usa una IA externa de respaldo.

## Piper o Qwen no disponible

Para Piper, descarga Davefx mediante el instalador. Para Qwen, activa su perfil,
prepara el modelo y añade una voz con transcripción. Si cambias `QWENTTS_PORT`,
ajusta el enlace `QWENTTS_PUBLIC_URL`. Las voces se gestionan en la web; el servicio
Qwen es opcional y no se necesita para producir con Piper.

## CPU ocupada o memoria insuficiente

Comprueba si está trabajando Qwen o Gemma. La producción es secuencial y Qwen usa
fragmentos, pero un procesador lento puede tardar más de una hora en un lote. Usa
Piper, reduce el lote o amplía la frecuencia si necesitas más descanso. Respeta la
noticia en curso al cambiar o reiniciar; no borres SQLite ni sus archivos WAL.

## Puerto ocupado

Usa otros `DASHBOARD_PORT`, `NEWS_RADIO_PORT` y `QWENTTS_PORT` en `.env` y recrea.
Las conexiones internas no cambian, porque usan nombres y puertos de servicio.

## No hay logo o intro

Son recursos opcionales. El texto y color siguen renderizándose sin logos.
Descárgalos explícitamente o aporta imágenes propias. Añade intros MP3 al directorio
documentado y activa la opción; no se incluyen los audios personales del autor.

## YouTube no muestra el directo

Comprueba el perfil `youtube`, el panel del orquestador y la clave seleccionada en
YouTube Studio. La recepción de señal y el inicio público son estados diferentes.
No pegues la clave ni URLs RTMPS completas al abrir una incidencia. Los registros
del módulo la ocultan, pero revisa cualquier captura antes de compartirla.
