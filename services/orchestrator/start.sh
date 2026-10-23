#!/usr/bin/env bash
# Start the three news projects in dependency order, without changing settings.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECTS_DIR="$(dirname -- "$SCRIPT_DIR")"
NEWS_DIR="$PROJECTS_DIR/news-radio"
QWEN_DIR="$PROJECTS_DIR/qwentts"
START_TIMEOUT=120
BUILD_ARGS=()
PHASE="comprobaciones iniciales"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

on_error() {
  local code=$?
  trap - ERR
  printf '\nArranque interrumpido durante: %s. Algunos servicios pueden haber quedado activos.\n' "$PHASE" >&2
  exit "$code"
}
trap on_error ERR

usage() {
  cat <<'HELP'
Uso: ./start.sh [--build]

Arranca Ollama, News Radio y el orquestador con la emisión local.
La API ligera de Qwen se arranca también con Piper para gestionar las voces.
El modelo de Qwen solo se carga cuando se solicita una locución con ese motor.
Con Piper se comprueba que su voz ya esté descargada.

  --build  Reconstruye las imágenes antes de arrancar.
  --help   Muestra esta ayuda sin iniciar servicios.

El arranque reanuda la producción automática si está habilitada en channel.json.
La salida a YouTube conserva su configuración guardada.
HELP
}

while (($#)); do
  case "$1" in
    --build) BUILD_ARGS=(--build) ;;
    --help|-h) usage; exit 0 ;;
    *) die "Opción no reconocida: $1. Usa --help." ;;
  esac
  shift
done

for required_command in docker python3; do
  command -v "$required_command" >/dev/null || die "No se encuentra $required_command."
done
docker compose version >/dev/null
docker info >/dev/null 2>&1 || die "Docker no responde o tu usuario no tiene permiso para utilizarlo."

compose() {
  local project_dir=$1
  shift
  docker compose --project-directory "$project_dir" --project-name "${project_dir##*/}" \
    -f "$project_dir/compose.yaml" -f "$project_dir/compose.dev.yaml" "$@"
}

for project in "$NEWS_DIR" "$QWEN_DIR" "$SCRIPT_DIR"; do
  [[ -f "$project/compose.yaml" && -f "$project/compose.dev.yaml" ]] || die "Faltan los archivos Compose en $project."
  compose "$project" config --quiet
done

# Read configuration through the app validator; never execute .env as shell code.
# Compose supplies the effective Ollama settings, including .env overrides.
DETAILS="$(CONFIG_DIR="$SCRIPT_DIR/config" DATA_DIR="$SCRIPT_DIR/data" \
  PYTHONPATH="$SCRIPT_DIR/src" python3 - "$NEWS_DIR" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
from news_orchestrator import config, piper_assets

try:
    settings = config.load()
    if settings['tts_engine'] == 'piper':
        piper_assets.voice(settings['piper_voice'], require_ready=True)
    root = Path(sys.argv[1])
    result = subprocess.run(['docker', 'compose', '--project-directory', str(root),
        '--project-name', root.name, '-f', str(root / 'compose.yaml'),
        '-f', str(root / 'compose.dev.yaml'), 'config', '--format', 'json'],
        check=True, capture_output=True, text=True)
    environment = json.loads(result.stdout)['services']['news-radio']['environment']
    values = [settings['tts_engine'], environment['OLLAMA_URL'], environment['OLLAMA_MODEL']]
    if any(not isinstance(value, str) or not value or '\n' in value or '\r' in value for value in values):
        raise ValueError('Configuración de arranque no válida.')
    print('\n'.join(values))
except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
    print(f'No se puede preparar el arranque: {exc}', file=sys.stderr)
    sys.exit(1)
PY
)"
mapfile -t VALUES <<< "$DETAILS"
TTS_ENGINE=${VALUES[0]}
OLLAMA_ENDPOINT=${VALUES[1]}
EDITORIAL_MODEL=${VALUES[2]}

ollama_responds() {
  python3 - "$OLLAMA_ENDPOINT" <<'PY'
import json
import sys
from urllib.request import urlopen
try:
    with urlopen(sys.argv[1].rstrip('/') + '/api/tags', timeout=3) as response:
        data = json.load(response)
    sys.exit(0 if isinstance(data, dict) and isinstance(data.get('models'), list) else 1)
except (OSError, ValueError):
    sys.exit(1)
PY
}

PHASE="arranque de Ollama"
printf '\n[1/4] Preparando Ollama…\n'
if ! ollama_responds; then
  # Only control the local standard Ollama service, never a remote instance.
  if ! python3 - "$OLLAMA_ENDPOINT" <<'PY'
import sys
from urllib.parse import urlsplit
try:
    url = urlsplit(sys.argv[1])
    local = url.hostname in {'localhost', '127.0.0.1', '::1'} and url.port == 11434
    sys.exit(0 if local else 1)
except ValueError:
    sys.exit(1)
PY
  then
    die "El Ollama configurado no responde. Arranca esa instancia y vuelve a ejecutar el script."
  fi
  command -v systemctl >/dev/null || die "No hay systemctl. Arranca Ollama manualmente y vuelve a intentarlo."
  if ! systemctl is-active --quiet ollama; then
    if ((EUID == 0)); then
      systemctl start ollama
    else
      command -v sudo >/dev/null || die "Se necesita permiso para arrancar ollama.service."
      printf 'Ollama está detenido; sudo puede solicitar tu contraseña.\n'
      sudo systemctl start ollama
    fi
  fi
fi
python3 - "$OLLAMA_ENDPOINT" "$EDITORIAL_MODEL" "$START_TIMEOUT" <<'PY'
import json
import sys
import time
from urllib.request import urlopen
deadline = time.monotonic() + int(sys.argv[3])
while time.monotonic() < deadline:
    try:
        with urlopen(sys.argv[1].rstrip('/') + '/api/tags', timeout=3) as response:
            data = json.load(response)
    except (OSError, ValueError):
        time.sleep(2)
        continue
    models = {model.get('name') for model in data.get('models', [])}
    if sys.argv[2] not in models:
        print(f'Falta el modelo editorial en Ollama: {sys.argv[2]}. Descárgalo antes de arrancar.', file=sys.stderr)
        sys.exit(1)
    print('Ollama disponible y modelo editorial instalado.')
    sys.exit(0)
print('Ollama no respondió dentro del tiempo de espera.', file=sys.stderr)
sys.exit(1)
PY

wait_service() {
  local project_dir=$1 service=$2 container state health
  local deadline=$((SECONDS + START_TIMEOUT))
  container="$(compose "$project_dir" ps --all --quiet "$service")"
  [[ -n "$container" ]] || die "No se encuentra el contenedor de $service."
  printf 'Esperando a %s…\n' "$service"
  while ((SECONDS < deadline)); do
    read -r state health < <(docker inspect --format \
      '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")
    if [[ "$state" == running && ( "$health" == healthy || "$health" == none ) ]]; then
      printf '%s disponible.\n' "$service"
      return
    fi
    [[ "$state" != exited && "$state" != dead ]] || die "$service se ha detenido. Revisa sus registros con docker compose logs."
    sleep 2
  done
  die "$service no quedó disponible en ${START_TIMEOUT} segundos."
}

PHASE="arranque de News Radio"
printf '\n[2/4] Arrancando News Radio…\n'
compose "$NEWS_DIR" up -d "${BUILD_ARGS[@]}" news-radio
wait_service "$NEWS_DIR" news-radio

PHASE="preparación del motor de voz"
printf '\n[3/4] Arrancando la biblioteca y API ligera de Qwen TTS…\n'
compose "$QWEN_DIR" up -d "${BUILD_ARGS[@]}" qwentts
wait_service "$QWEN_DIR" qwentts
if [[ "$TTS_ENGINE" == qwen ]]; then
  compose "$QWEN_DIR" exec -T qwentts python -c \
    'from qwentts.config import model_ready; import sys; sys.exit(0 if model_ready() else "Falta el modelo de Qwen. Revisa su instalación.")'
else
  printf 'Piper seleccionado. Su voz está disponible; Qwen conserva únicamente su API y biblioteca en espera.\n'
fi

PHASE="arranque del orquestador y la emisión"
printf '\n[4/4] Arrancando el orquestador y la emisión…\n'
compose "$SCRIPT_DIR" up -d "${BUILD_ARGS[@]}" orchestrator broadcaster youtube
for service in orchestrator broadcaster youtube; do
  wait_service "$SCRIPT_DIR" "$service"
done

printf '\nSistema arrancado. Motor de voz: %s\n' "$TTS_ENGINE"
printf 'Panel: http://192.168.1.62:8792\n'
