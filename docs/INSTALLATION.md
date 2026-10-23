# Instalación

## Preparación

Instala Docker Engine, el plugin Docker Compose y Python 3.12+. Ejecuta los scripts
con el usuario que administrará los datos, no con `sudo`: al crear `.env` se toma
su UID/GID. La administración de Docker debe estar disponible para ese usuario.

```bash
./scripts/install.sh --tts piper
```

Piper se ejecuta como proceso temporal del orquestador. No necesita el contenedor
Qwen ni una referencia de voz. El instalador descarga Davefx desde la revisión
fijada del catálogo, comprobando tamaño y SHA-256.

El modelo inicial es el que usa el proyecto original:
`hf.co/lmstudio-community/gemma-4-E2B-it-GGUF:Q4_K_M`. Cambia `OLLAMA_MODEL` antes
de instalar si deseas otro modelo compatible con las salidas JSON utilizadas.
La posibilidad de descargarlo depende de su disponibilidad y condiciones en origen.
Un cambio de etiqueta de modelo no certifica su calidad: comprueba los guiones.

La imagen de Ollama está fijada por versión y digest en `.env.example`; las
dependencias directas Python y las revisiones de las voces ya están fijadas en cada servicio.
Las bases Python también quedan fijadas por digest a la base de la versión funcional.
Los paquetes del sistema se obtienen de sus repositorios durante el build; no se
afirma una reproducción bit a bit de todas las dependencias.

## Qwen

En una instalación nueva:

```bash
./scripts/install.sh --tts qwen
```

Activa el perfil `qwen`, construye su imagen CPU y descarga la revisión fijada de
`Qwen/Qwen3-TTS-12Hz-0.6B-Base`. Usa float32 y los fragmentos lógicos ya existentes.
La descarga no incluye ninguna voz de una persona.

En una instalación que ya usa Piper:

1. Añade `qwen` a `COMPOSE_PROFILES` en `.env`.
2. Ejecuta `./scripts/install.sh --tts qwen` para preparar el servicio y su modelo.
3. Añade una referencia y su texto desde la biblioteca web.
4. Selecciona Qwen y una voz activa en el dashboard.

La configuración existente no se reemplaza al reinstalar. Conservar Piper como
alternativa no requiere volver a descargar su voz.

## Primer arranque sin scripts

```bash
cp .env.example .env
# Ajusta APP_UID y APP_GID al resultado de id -u e id -g.
docker compose build
docker compose run --rm --no-deps bootstrap
docker compose up -d --wait ollama
docker compose exec ollama ollama pull 'hf.co/lmstudio-community/gemma-4-E2B-it-GGUF:Q4_K_M'
docker compose run --rm --no-deps --entrypoint python orchestrator -m news_orchestrator.piper_assets
docker compose up -d
```

`docker compose up -d` inicializa las carpetas y arranca la infraestructura, pero
no descarga pesos de IA implícitamente. Para preparar solo infraestructura existe
`./scripts/install.sh --skip-models`: no significa que la producción esté lista.

## YouTube opcional

1. Habilita emisiones por codificador en tu canal de YouTube Studio.
2. Añade `youtube` a `COMPOSE_PROFILES`; si usas Qwen, el valor es `qwen,youtube`.
3. Ejecuta `./scripts/start.sh`.
4. En el panel YouTube guarda la clave de emisión y solicita enviar señal.
5. Comprueba en YouTube Studio la recepción, visibilidad e inicio del directo.

Arrancar el perfil no activa por sí solo una emisión nueva. Las credenciales se
guardan en `state/orchestrator/data/youtube/`, nunca en Git. Al restaurar una copia,
sí puede conservarse una salida que estuviera activada: revisa antes de arrancar.

## Referencias

- [Docker: perfiles](https://docs.docker.com/compose/how-tos/profiles/)
- [Docker: orden y salud de dependencias](https://docs.docker.com/compose/how-tos/startup-order/)
- [Ollama: imagen oficial y CPU](https://docs.ollama.com/docker)
