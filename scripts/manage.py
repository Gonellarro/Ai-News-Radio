"""Standard-library lifecycle CLI. Never sources .env as executable shell code."""

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def initial_env():
    path = Path(os.environ.get('STACK_ENV_FILE', ROOT / '.env')).resolve()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT / '.env.example').read_text()
        text = text.replace('APP_UID=1000', f'APP_UID={os.getuid()}').replace('APP_GID=1000', f'APP_GID={os.getgid()}')
        path.write_text(text)
        path.chmod(0o600)
    return path


def edit_env(path, changes):
    lines = path.read_text().splitlines()
    for key, value in changes.items():
        replacement = key + '=' + value
        indexes = [i for i, line in enumerate(lines) if line.startswith(key + '=')]
        if indexes:
            lines[indexes[-1]] = replacement
        else:
            lines.append(replacement)
    path.write_text('\n'.join(lines) + '\n')


class Stack:
    def __init__(self, dev=False):
        if not shutil.which('docker'):
            raise RuntimeError('Instala Docker Engine y Docker Compose antes de continuar.')
        self.env = initial_env()
        self.command = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(self.env), '-f', str(ROOT / 'compose.yaml')]
        if dev:
            self.command += ['-f', str(ROOT / 'compose.dev.yaml')]
        self.run('version', capture=True)

    def run(self, *args, capture=False):
        result = subprocess.run(self.command + list(args), cwd=ROOT, check=True,
                                text=True, stdout=subprocess.PIPE if capture else None)
        return result.stdout if capture else None

    def config(self):
        return json.loads(self.run('config', '--format', 'json', capture=True))

    def state(self):
        for volume in self.config()['services']['bootstrap']['volumes']:
            if volume['target'] == '/state':
                return Path(volume['source'])
        raise RuntimeError('No se encuentra el directorio de estado.')

    def address(self):
        port = self.config()['services']['orchestrator']['ports'][0]
        host = port.get('host_ip', '127.0.0.1')
        if host in {'0.0.0.0', '::'}:
            host = '127.0.0.1'
        if ':' in host:
            host = '[' + host + ']'
        return f'http://{host}:{port["published"]}'

    def running(self):
        return self.run('--profile', '*', 'ps', '--status', 'running', '-q', capture=True).strip()


def request(base, path, payload=None):
    req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def install(stack, args):
    if args.tts:
        # Existing channel settings are deliberately not overwritten.
        config = stack.config()
        profiles = {'qwen'} if args.tts == 'qwen' else set()
        current = next((line.split('=', 1)[1] for line in stack.env.read_text().splitlines() if line.startswith('COMPOSE_PROFILES=')), '')
        profiles.update(p for p in current.split(',') if p and p != 'qwen')
        edit_env(stack.env, {'TTS_ENGINE': args.tts, 'COMPOSE_PROFILES': ','.join(sorted(profiles))})
    stack.run('config', '--quiet')
    stack.run('build')
    stack.run('run', '--rm', '--no-deps', 'bootstrap')
    stack.run('up', '-d', '--wait', '--wait-timeout', '180', 'ollama')
    if not args.skip_models:
        model = stack.config()['services']['ollama']['environment']['OLLAMA_MODEL']
        stack.run('exec', '-T', 'ollama', 'ollama', 'pull', model)
        stack.run('run', '--rm', '--no-deps', '--entrypoint', 'python', 'orchestrator', '-m', 'news_orchestrator.piper_assets')
        if 'qwentts' in stack.config()['services']:
            stack.run('run', '--rm', '--no-deps', '--entrypoint', 'python', 'qwentts', '-m', 'qwentts.download')
    stack.run('up', '-d', '--wait', '--wait-timeout', '240')
    print('Dashboard:', stack.address())
    channel = json.loads((stack.state() / 'orchestrator/config/channel.json').read_text())
    print('Motor guardado en el canal:', channel['tts_engine'])
    print('Automatización:', 'activa' if channel['enabled'] else 'pausada; puedes activarla en Panel de control.')
    if args.skip_models:
        print('No se han descargado modelos en esta ejecución. Comprueba su disponibilidad antes de producir; install.sh sin --skip-models prepara las descargas.')


def stop(stack, args):
    if not stack.running():
        return
    channel = stack.state() / 'orchestrator/config/channel.json'
    was_enabled = False
    if not args.force:
        try:
            snapshot = request(stack.address(), '/api/dashboard/config')
            was_enabled = snapshot['settings']['enabled']
            if was_enabled:
                request(stack.address(), '/api/dashboard/config', {'revision': snapshot['revision'], 'changes': {'enabled': False}})
        except (URLError, OSError) as exc:
            raise RuntimeError('No se puede coordinar la parada con el dashboard. Revisa el servicio o usa --force explícitamente.') from exc
        print('Esperando al final de la noticia completa y de las valoraciones en curso…', flush=True)
        deadline = time.monotonic() + args.timeout
        while True:
            status = request(stack.address(), '/api/status')
            relevance = request(stack.address(), '/api/dashboard/relevance')
            busy = (status['active_id'] or status['presentation_active_id'] or status['scanning']
                    or relevance['active'] or relevance.get('manual', {}).get('status') in {'queued', 'waiting_production', 'waiting_ai', 'running'})
            editorial = stack.run('exec', '-T', 'news-radio', 'python', '-c',
                                  "import urllib.request,json; x=json.load(urllib.request.urlopen('http://127.0.0.1:8790/api/editorial')); print(bool(x['active_id'] or any(d['status']=='generating' for d in x['drafts'])))", capture=True)
            busy = busy or editorial.strip() == 'True'
            if 'qwentts' in stack.config()['services']:
                raw = stack.run('exec', '-T', 'qwentts', 'python', '-c',
                                "import urllib.request,json; x=json.load(urllib.request.urlopen('http://127.0.0.1:8791/api/jobs')); print(any(j['status'] in {'preparing','queued','waiting','running'} for j in x['jobs']))", capture=True)
                busy = busy or raw.strip() == 'True'
            if not busy:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('Se agotó la espera; no se ha interrumpido el trabajo. Automatización pausada; revisa el dashboard antes de reintentar.')
            time.sleep(5)
    stack.run('--profile', '*', 'stop', '--timeout', '30')
    if was_enabled and channel.exists():
        value = json.loads(channel.read_text())
        value['enabled'] = True
        temporary = channel.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(channel)
    print('Servicios detenidos. Los datos y el estado de automatización se conservan.')


def backup(stack, args):
    if stack.running():
        raise RuntimeError('Para una copia coherente, ejecuta primero ./scripts/stop.sh. La copia no detiene ni interrumpe servicios por su cuenta.')
    state = stack.state()
    if not state.is_dir():
        raise RuntimeError('Todavía no hay datos que copiar.')
    folder = ROOT / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    target = folder / ('ai-news-radio-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.tar.gz')
    excluded = {'state/ollama', 'state/qwentts/models'} if not args.include_models else set()
    def filter_member(member):
        relative = PurePosixPath(member.name).relative_to('state')
        original = state.joinpath(*relative.parts)
        if original.is_symlink() or member.issym() or member.islnk():
            raise RuntimeError('La copia contiene un enlace inesperado: ' + member.name)
        if any(member.name == p or member.name.startswith(p + '/') for p in excluded):
            return None
        return member
    try:
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        # HLS intentionally uses hardlinks; archive their contents independently.
        # Reject symbolic links by inspecting the source path in filter_member.
        with os.fdopen(descriptor, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz', dereference=True) as archive:
            archive.add(state, arcname='state', filter=filter_member)
            archive.add(stack.env, arcname='runtime.env')
            raw = json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'includes_models': args.include_models}).encode()
            entry = tarfile.TarInfo('backup.json'); entry.size = len(raw); archive.addfile(entry, io.BytesIO(raw))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print('Copia privada:', target)


def restore(stack, args):
    if stack.running():
        raise RuntimeError('Detén los servicios antes de restaurar.')
    state = stack.state()
    if state.exists() and any(state.iterdir()):
        raise RuntimeError('La restauración requiere un STATE_DIR vacío. Conserva o mueve tus datos actuales antes de continuar.')
    state.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=state.parent, prefix='.restore-') as directory:
        with tarfile.open(args.archive, 'r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in {'state', 'runtime.env', 'backup.json'} or not (member.isfile() or member.isdir()):
                    raise RuntimeError('Contenido no admitido en la copia: ' + member.name)
            archive.extractall(directory, members=members, filter='data')
        source = Path(directory) / 'state'
        if not source.is_dir():
            raise RuntimeError('La copia no contiene el estado de la aplicación.')
        if state.exists():
            state.rmdir()
        source.rename(state)
        saved_env = Path(directory) / 'runtime.env'
        if saved_env.exists():
            shutil.copyfile(saved_env, ROOT / '.env.restored')
            (ROOT / '.env.restored').chmod(0o600)
    print('Datos restaurados. Revisa .env.restored; tu .env actual no se ha sobrescrito.')
    print('Si la copia excluía modelos, ejecuta install.sh para recuperarlos. YouTube puede conservar una salida activada en la copia.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    install_parser = commands.add_parser('install'); install_parser.add_argument('--tts', choices=['piper', 'qwen']); install_parser.add_argument('--skip-models', action='store_true')
    start_parser = commands.add_parser('start'); start_parser.add_argument('--dev', action='store_true')
    stop_parser = commands.add_parser('stop'); stop_parser.add_argument('--force', action='store_true'); stop_parser.add_argument('--timeout', type=int, default=10800)
    backup_parser = commands.add_parser('backup'); backup_parser.add_argument('--include-models', action='store_true')
    restore_parser = commands.add_parser('restore'); restore_parser.add_argument('archive', type=Path)
    commands.add_parser('status'); commands.add_parser('logos')
    args = parser.parse_args()
    stack = Stack(getattr(args, 'dev', False))
    if args.action == 'install': install(stack, args)
    elif args.action == 'start':
        stack.run('up', '-d', '--build', '--wait', '--wait-timeout', '240'); print('Dashboard:', stack.address())
    elif args.action == 'stop': stop(stack, args)
    elif args.action == 'backup': backup(stack, args)
    elif args.action == 'restore': restore(stack, args)
    elif args.action == 'status':
        stack.run('ps'); print('Dashboard:', stack.address())
    elif args.action == 'logos':
        stack.run('run', '--rm', '--no-deps', '--entrypoint', 'python', 'orchestrator', '-m', 'news_orchestrator.logo_assets')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print('Error:', exc, file=sys.stderr)
        raise SystemExit(1)
