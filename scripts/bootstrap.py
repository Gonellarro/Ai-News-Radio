"""Idempotent first-run configuration and directory ownership inside Docker."""

import json
import os
from pathlib import Path
import shutil


def main():
    root = Path('/state')
    uid, gid = int(os.environ['APP_UID']), int(os.environ['APP_GID'])
    engine = os.environ.get('TTS_ENGINE', 'piper')
    if engine not in {'piper', 'qwen'}:
        raise ValueError('TTS_ENGINE debe ser piper o qwen.')
    for relative in ('news-radio/config', 'news-radio/data', 'orchestrator/config',
                     'orchestrator/data/intros', 'orchestrator/data/branding/logos',
                     'orchestrator/data/branding/originals', 'qwentts/models',
                     'qwentts/voices', 'qwentts/data', 'ai-runtime', 'ollama'):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        # Change only the managed directories, never recurse through user data.
        for managed in (path, *[parent for parent in path.parents if root in parent.parents or parent == root]):
            os.chown(managed, uid, gid)
    for service in ('news-radio', 'orchestrator'):
        for source in (Path('/defaults') / service).iterdir():
            if not source.is_file():
                continue
            target = root / service / 'config' / source.name
            if target.exists():
                continue  # Web edits and imported configuration always win.
            if service == 'orchestrator' and source.name == 'channel.json':
                value = json.loads(source.read_text())
                value.update(tts_engine=engine,
                             enabled=os.environ.get('INITIAL_AUTOMATION_ENABLED', 'false').lower() == 'true',
                             channel_name=os.environ.get('CHANNEL_NAME', value['channel_name']),
                             topic=os.environ.get('CHANNEL_TOPIC', value['topic']),
                             schedule_timezone=os.environ.get('SCHEDULE_TIMEZONE', 'Europe/Madrid'))
                target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            else:
                shutil.copyfile(source, target)
            os.chown(target, uid, gid)
    print('Configuración y directorios preparados; ajustes existentes conservados.')


if __name__ == '__main__':
    main()
