"""Local Piper voice catalogue and explicit, verified downloads."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.request import Request, urlopen

from news_orchestrator import config

REPOSITORY = "https://huggingface.co/rhasspy/piper-voices"


def catalogue():
    data = json.loads((config.CONFIG / "piper_voices.json").read_text())
    entries = data.get("voices") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("piper_voices.json debe contener una lista voices.")
    voices = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", entry.get("id", ""))
                or entry["id"] in voices or not re.fullmatch(r"[a-f0-9]{40}", entry.get("revision", ""))):
            raise ValueError("Identificador o revisión de voz Piper no válidos.")
        for key in ("name", "label", "language"):
            if not isinstance(entry.get(key), str) or not 1 <= len(entry[key]) <= 120:
                raise ValueError(f"Falta {key} en la voz Piper.")
        path = PurePosixPath(entry.get("base_path", ""))
        if path.is_absolute() or ".." in path.parts or not re.fullmatch(r"[A-Za-z0-9_/-]+", str(path)):
            raise ValueError("Ruta de descarga Piper no válida.")
        for key in ("model", "config", "card"):
            asset = entry.get("files", {}).get(key, {})
            if (not re.fullmatch(r"[A-Za-z0-9_.-]+", asset.get("name", "")) or asset.get("name") in {".", ".."}
                    or type(asset.get("size")) is not int or not 0 < asset["size"] <= 128 * 1024 * 1024
                    or not re.fullmatch(r"[a-f0-9]{64}", asset.get("sha256", ""))):
                raise ValueError("Archivo o huella de voz Piper no válidos.")
        voices[entry["id"]] = entry
    return voices


def directory(voice_id):
    return config.DATA / "piper" / voice_id


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def voice(voice_id, require_ready=False, verify=False):
    selected = catalogue().get(voice_id)
    if selected is None:
        raise ValueError("La voz de Piper no está en config/piper_voices.json.")
    folder = directory(voice_id)
    ready = not folder.is_symlink()
    for asset in selected["files"].values():
        path = folder / asset["name"]
        ready = ready and path.is_file() and not path.is_symlink() and path.stat().st_size == asset["size"]
        if ready and verify and digest(path) != asset["sha256"]:
            ready = False
    if require_ready and not ready:
        raise RuntimeError("Falta la voz de Piper o no coincide con su catálogo. Ejecuta la descarga de piper_assets.")
    return {**selected, "ready": ready}


def public_catalogue():
    return [{key: entry[key] for key in ("id", "name", "label", "language", "ready")}
            for voice_id in catalogue() for entry in [voice(voice_id)]]


def download(voice_id):
    selected = voice(voice_id)
    folder = directory(voice_id)
    if folder.is_symlink():
        raise ValueError("La carpeta de voz no puede ser un enlace.")
    folder.mkdir(parents=True, exist_ok=True)
    for asset in selected["files"].values():
        target = folder / asset["name"]
        if target.is_file() and not target.is_symlink() and digest(target) == asset["sha256"]:
            continue
        if target.is_symlink():
            raise ValueError("El archivo de voz no puede ser un enlace.")
        temporary = target.with_name(target.name + ".part")
        url = f"{REPOSITORY}/resolve/{selected['revision']}/{selected['base_path']}/{asset['name']}"
        request = Request(url, headers={"User-Agent": "NewsOrchestrator/1.0 (Piper voice download)"})
        print(f"Descargando {voice_id}: {asset['name']}", flush=True)
        try:
            with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                total = 0
                while chunk := response.read(65536):
                    total += len(chunk)
                    if total > asset["size"]:
                        raise ValueError("La voz supera el tamaño fijado en el catálogo.")
                    output.write(chunk)
            if total != asset["size"] or digest(temporary) != asset["sha256"]:
                raise ValueError("La descarga de Piper no coincide con su tamaño o SHA-256.")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return voice(voice_id, require_ready=True, verify=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("voice", nargs="?", default="es_ES-davefx-medium")
    args = parser.parse_args()
    selected = download(args.voice)
    print(f"Voz disponible: {selected['label']}")


if __name__ == "__main__":
    main()
