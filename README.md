# AI News Radio

Canal automático de noticias con recopilación de fuentes, redacción local,
locución, vídeo y parrilla continua. El audio es el contenido principal. Incluye
dashboard, emisión local HLS y una salida opcional a YouTube.

Un repositorio y un Docker Compose; servicios separados para poder desarrollar,
actualizar y limitar sus recursos de forma independiente. La instalación de
producción anterior no se modifica al preparar este proyecto.

## Inicio rápido

Requisitos: Linux amd64, Docker Engine con Compose v2.24 o posterior y Python 3.12 o
posterior para los scripts. El código también puede arrancarse directamente con
Compose. Esta distribución inicial usa CPU; no requiere GPU.

```bash
git clone <URL_DEL_REPOSITORIO>
cd ai-news-radio
./scripts/install.sh --tts piper
```

El instalador crea `.env`, construye las imágenes, prepara directorios, descarga
el modelo configurado de Ollama y la voz Davefx y arranca los servicios. Las
descargas iniciales necesitan Internet, espacio y tiempo. No descarga noticias
en audio hasta activar el canal.

Abre **http://localhost:8792**. En **Panel de control**, revisa tema, idioma,
capacidad y horario; activa la automatización y utiliza **Revisar noticias ahora**
para iniciar el primer lote sin esperar a la siguiente hora. No hay moderación
manual. Los errores técnicos conservan los reintentos y sus límites.

Una vez instalado:

```bash
docker compose up -d
# O bien:
./scripts/start.sh
./scripts/status.sh
./scripts/stop.sh
```

Por defecto, los puertos solo se publican en el equipo local. Para acceder desde
una LAN de confianza, cambia `BIND_ADDRESS=0.0.0.0` en `.env` y recrea los servicios.
El dashboard administra el canal y no incorpora autenticación; no se configura
una publicación directa a Internet.

## Modalidades

| Modalidad | Configuración | Recursos de voz |
| --- | --- | --- |
| Piper | Predeterminada | Davefx, español; rápida y ligera |
| Qwen | `./scripts/install.sh --tts qwen` en instalación nueva | Modelo oficial 0.6B y biblioteca de voces propia |
| YouTube | Añadir `youtube` a `COMPOSE_PROFILES` | Misma parrilla local, salida RTMPS |

En Qwen añade una referencia y su transcripción desde **Voces y producción** o
desde http://localhost:8791. No se distribuyen voces personales. Para cambiar
un sistema ya instalado, sigue [la configuración](docs/CONFIGURATION.md): los
valores de `.env` no sobrescriben los ajustes guardados en el dashboard.

Como orientación inicial, reserva 8 GB de RAM para Piper con un modelo pequeño;
16 GB dan más margen con Qwen. El sistema anterior trabajaba en 8 GB usando los
modelos por turnos. Los límites no son reservas ni garantizan que cualquier
modelo quepa. El rendimiento depende del equipo y de la longitud del texto.
Reserva aproximadamente 15–25 GB de disco para imágenes, modelos y operación;
consulta el tamaño de tus modelos y conserva margen libre.

## Funcionamiento

1. El colector lee fuentes concretas y redes públicas con sus intervalos y pausas.
   SearXNG es un complemento opcional, desactivado inicialmente.
2. Cada franja del calendario abre un lote. Por defecto son cinco incorporaciones
   por hora, una tras otra, hasta terminar o quedarse sin material utilizable.
3. El balance de fuentes y la valoración editorial opcional eligen candidatas.
   Solo las seleccionadas reciben resumen, traducción y locución.
4. Ollama redacta sin razonamiento visible y libera el modelo al acabar. Un
   bloqueo compartido evita solapar las inferencias gestionadas por este sistema.
5. Piper o Qwen produce la voz; se normaliza y se añaden las pausas configuradas.
   Las intros musicales son opcionales y requieren tus propios archivos.
6. Cada vídeo terminado entra en la parrilla y sustituye a la noticia que lleve
   más tiempo en ella, excepto las fijadas manualmente. Los archivos retirados
   se borran después de finalizar su reproducción.
7. La emisión local continúa durante la producción. YouTube se activa por separado.

El objetivo de cinco por hora depende de tener material y capacidad de producción;
no se duplica contenido ni se acumulan infinitos lotes para aparentar ese ritmo.

## Estructura

```text
compose.yaml              Servicios y límites de recursos
compose.dev.yaml          Montajes del código para desarrollar
.env.example              Instalación y opciones de contenedores
config/examples/          Configuraciones iniciales públicas
services/news-radio/      Fuentes y redacción con Ollama
services/orchestrator/    Dashboard, producción, Piper y emisión
services/qwentts/         Clonación y síntesis por fragmentos
scripts/                  Instalación, arranque y copias
docs/                     Operación y arquitectura
state/                    Datos locales; excluidos de Git
backups/                  Copias privadas; excluidas de Git
```

## Documentación

- [Instalación y modalidades](docs/INSTALLATION.md)
- [Configuración, fuentes y voces](docs/CONFIGURATION.md)
- [Arquitectura y persistencia](docs/ARCHITECTURE.md)
- [Operación, actualizaciones y copias](docs/OPERATIONS.md)
- [Desarrollo](docs/DEVELOPMENT.md)
- [Diagnóstico](docs/TROUBLESHOOTING.md)
- [Migración desde la instalación anterior](docs/MIGRATION.md)
- [Preparar y publicar el repositorio](docs/PUBLISHING.md)
- [Comprobaciones realizadas y límites](docs/VERIFICATION.md)
- [Origen y versiones conservadas](docs/SOURCE_HISTORY.json)

## Estado y licencia

Se conserva el historial de los tres proyectos y sus etiquetas bajo `legacy/`.
La base del orquestador es `1.1.Totalmente-Funcional`; el empaquetado unificado
añade configuración portable y scripts sin sustituir la instalación en emisión.

El código propio se distribuye bajo [MIT](LICENSE), elegida por su autor. Los modelos, librerías, voces,
logotipos y noticias mantienen las condiciones de sus respectivos titulares;
sus pesos y audios personales no forman parte de este repositorio.
