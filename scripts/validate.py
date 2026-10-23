"""Offline syntax and packaging checks; no inference, feeds or live services."""

import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    count = 0
    for folder in (ROOT / 'services', ROOT / 'scripts'):
        for path in folder.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            ast.parse(path.read_text(), filename=str(path)); count += 1
    for path in (ROOT / 'config/examples').rglob('*.json'):
        json.loads(path.read_text())
    for path in (ROOT / 'scripts').glob('*.sh'):
        subprocess.run(['bash', '-n', str(path)], check=True)
    if len(sys.argv) > 1:
        raise SystemExit('validate.py no acepta argumentos.')
    print(f'Sintaxis de {count} archivos Python, JSON y scripts Bash correcta.')


if __name__ == '__main__':
    main()
