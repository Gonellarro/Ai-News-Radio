"""Reference recordings and transcripts; no model is needed to manage them."""

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from qwentts.config import VOICES


def probe(path):
    run = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=20)
    try:
        seconds = float(json.loads(run.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("No se pudo leer el audio. Utiliza WAV, MP3, FLAC, OGG o M4A.") from exc
    if not 3 <= seconds <= 30:
        raise ValueError("La referencia debe durar entre 3 y 30 segundos. Recomendamos entre 6 y 15.")
    return seconds


class Voices:
    def __init__(self):
        VOICES.mkdir(parents=True, exist_ok=True)
        (VOICES / "library").mkdir(exist_ok=True)

    def get(self, voice_id):
        if not isinstance(voice_id, str) or len(voice_id) != 32 or any(c not in "0123456789abcdef" for c in voice_id):
            raise ValueError("Selecciona una voz guardada.")
        path = VOICES / "library" / voice_id / "voice.json"
        if not path.is_file():
            raise ValueError("No se encuentra esa voz.")
        return json.loads(path.read_text())

    def list(self):
        return sorted([json.loads(path.read_text()) for path in (VOICES / "library").glob("*/voice.json")],
                      key=lambda voice: voice["name"].casefold())

    def add_file(self, path, name, transcript, voice_id=None, source=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Escribe un nombre de voz de hasta 100 caracteres.")
        if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 3000:
            raise ValueError("Añade la transcripción literal de la referencia (hasta 3.000 caracteres).")
        seconds = probe(path)
        voice_id = voice_id or uuid.uuid4().hex
        directory = VOICES / "library" / voice_id
        directory.mkdir(exist_ok=True)
        target = directory / "reference.wav"
        run = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(path),
                              "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target)],
                             capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise ValueError("No se pudo convertir la muestra a WAV.")
        voice = {"id": voice_id, "name": name.strip(), "transcript": transcript.strip(),
                 "duration_seconds": round(seconds, 2), "reference": str(target), "source": source}
        temporary = directory / "voice.tmp"
        temporary.write_text(json.dumps(voice, ensure_ascii=False, indent=2))
        temporary.replace(directory / "voice.json")
        return voice

    def upload(self, data):
        audio = data.get("audio_base64")
        if not isinstance(audio, str) or len(audio) > 16 * 1024 * 1024:
            raise ValueError("El archivo no puede superar los 12 MiB.")
        try:
            raw = base64.b64decode(audio, validate=True)
        except ValueError as exc:
            raise ValueError("El audio no tiene una codificación válida.") from exc
        with tempfile.TemporaryDirectory(prefix="voice-") as temporary:
            path = Path(temporary) / "upload.audio"
            path.write_bytes(raw)
            return self.add_file(path, data.get("name"), data.get("transcript"))

    def import_folder(self):
        imported, errors = [], []
        for path in sorted(VOICES.iterdir()):
            if not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
                continue
            transcript_path = path.with_suffix(".txt")
            if not transcript_path.is_file():
                errors.append(f"Falta {transcript_path.name} para {path.name}")
                continue
            voice_id = hashlib.sha256(path.name.encode()).hexdigest()[:32]
            if (VOICES / "library" / voice_id / "voice.json").is_file():
                continue
            try:
                imported.append(self.add_file(path, path.stem, transcript_path.read_text(encoding="utf-8"),
                                              voice_id=voice_id, source=path.name))
            except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{path.name}: {exc}")
        return {"imported": imported, "errors": errors}
