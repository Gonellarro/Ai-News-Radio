# Comprobación del empaquetado — 23 de octubre de 2026

Se utilizó un proyecto Compose independiente (`ai-news-radio-check`), puertos
18890–18892 y directorios propios. Las fuentes estaban desactivadas y el canal
pausado para no duplicar peticiones externas ni cargar otro modelo de redacción.
La instalación original no se migró ni se detuvo.

## Comprobado

- Sintaxis de 73 archivos Python, configuraciones JSON y scripts Bash.
- Resolución de Compose base y de desarrollo con los perfiles Qwen y YouTube.
- Construcción de las tres imágenes propias a partir de sus Dockerfiles.
- Inicialización de carpetas, permisos y configuraciones desde cero.
- Un segundo bootstrap conservó un nombre de canal editado previamente.
- Salud de colector, orquestador, broadcaster, servicio Qwen y proceso YouTube.
- Los cinco trabajadores del orquestador estaban activos.
- Piper funcionó sin el servicio Qwen; su ausencia se mostró como opcional.
- Descarga de Davefx con comprobación de tamaños y SHA-256.
- Locución Piper real: 4,91 segundos de audio, 4,34 segundos de generación y
  aproximadamente 215 MiB de pico del proceso en este equipo.
- Render de una tarjeta y vídeo H.264/AAC, con dos segmentos HLS.
- Emisión HLS local de continuidad y resolución interna del colector y Ollama.
- El emisor YouTube tomó `http://orchestrator:8792/live/index.m3u8` y permaneció
  desactivado, sin clave ni envío público.
- Parada ordenada mediante el script, copia privada y restauración en otro directorio.
- Configuración, SQLite, voz y vídeo restaurados coincidieron byte a byte.
- Arranque saludable desde esa restauración.
- Instalador ejecutado con `--tts qwen --skip-models` sobre la restauración,
  conservando los ajustes del canal y dejando todos sus servicios saludables.
- Revisión de patrones de credenciales en los archivos públicos e historial importado,
  sin coincidencias encontradas. No sustituye una auditoría de seguridad completa.

## Límites de esta comprobación

El disco del servidor tenía unos 6,7 GB libres. La imagen oficial Ollama fijada
requiere unos 3,6 GB de descarga comprimida, más su espacio descomprimido. Para
proteger la instalación activa no se descargó allí: se comprobó su manifiesto y
digest oficial y se utilizó, solo en la instancia aislada, el binario Ollama 0.40.5
ya instalado sobre una imagen temporal. Esa imagen temporal no forma parte de la
distribución ni sustituye la imagen oficial en `compose.yaml` o `.env.example`.

No se descargó otro Gemma ni el checkpoint Qwen para repetir inferencias pesadas.
El arranque de Qwen se verificó sin pesos: informó correctamente `model_ready=false`.
No se hizo una nueva clonación real ni una publicación de comprobación en YouTube.
Esas funciones proceden de los servicios originales, y deben comprobarse de nuevo
al migrar datos o instalar en otro equipo con los modelos y las voces definitivas.

No se certifica una instalación universal en ARM, Windows, GPU o cualquier modelo
alternativo. El destino comprobado fue Linux amd64 con Docker Compose.
