"""Reference library. Managing recordings never loads the synthesis model."""

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
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


def atomic_json(path, value):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_details(name, transcript):
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ValueError("Escribe un nombre de voz de hasta 100 caracteres.")
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 3000:
        raise ValueError("Añade la transcripción literal de la referencia (hasta 3.000 caracteres).")


class Voices:
    def __init__(self):
        self.lock = threading.RLock()
        VOICES.mkdir(parents=True, exist_ok=True)
        for name in ("library", ".deleted"):
            path = VOICES / name
            if path.is_symlink():
                raise ValueError("La biblioteca contiene un enlace inesperado.")
            path.mkdir(exist_ok=True)

    def directory(self, voice_id):
        if not isinstance(voice_id, str) or len(voice_id) != 32 or any(c not in "0123456789abcdef" for c in voice_id):
            raise ValueError("Selecciona una voz guardada.")
        directory = VOICES / "library" / voice_id
        if directory.is_symlink():
            raise ValueError("La carpeta de voz contiene un enlace inesperado.")
        return directory

    def get(self, voice_id):
        with self.lock:
            directory = self.directory(voice_id)
            path = directory / "voice.json"
            if path.is_symlink() or not path.is_file():
                raise ValueError("No se encuentra esa voz.")
            voice = json.loads(path.read_text())
            reference = Path(voice["reference"])
            if reference.parent != directory or reference.is_symlink() or not reference.is_file():
                raise ValueError("La referencia de esta voz no está disponible.")
            return {**voice, "enabled": voice.get("enabled", True)}

    def list(self):
        with self.lock:
            return sorted([self.get(path.parent.name) for path in (VOICES / "library").glob("*/voice.json")
                           if not path.parent.name.startswith(".")], key=lambda voice: voice["name"].casefold())

    def unique_name(self, name, except_id=None):
        if any(v["id"] != except_id and v["name"].casefold() == name.strip().casefold() for v in self.list()):
            raise ValueError("Ya existe una voz con ese nombre. Edítala o elige otro nombre.")

    @staticmethod
    def convert(source, target):
        seconds = probe(source)
        run = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-protocol_whitelist", "file,pipe", "-i", str(source),
                              "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(target)],
                             capture_output=True, text=True, timeout=30)
        if run.returncode:
            raise ValueError("No se pudo convertir la muestra a WAV.")
        return round(seconds, 2)

    def add_file(self, path, name, transcript, voice_id=None, source=None):
        validate_details(name, transcript)
        voice_id = voice_id or uuid.uuid4().hex
        directory = self.directory(voice_id)
        with tempfile.TemporaryDirectory(prefix=".voice-", dir=VOICES / "library") as temporary:
            staged = Path(temporary)
            seconds = self.convert(path, staged / "reference.wav")
            voice = {"id": voice_id, "name": name.strip(), "transcript": transcript.strip(), "enabled": True,
                     "duration_seconds": seconds, "reference": str(directory / "reference.wav"), "source": source,
                     "updated_at": datetime.now(timezone.utc).isoformat()}
            atomic_json(staged / "voice.json", voice)
            with self.lock:
                self.unique_name(name)
                if directory.exists():
                    raise ValueError("Esta muestra ya está importada.")
                staged.rename(directory)
                (VOICES / ".deleted" / f"{voice_id}.json").unlink(missing_ok=True)
        return voice

    @staticmethod
    def uploaded_audio(audio, target):
        if not isinstance(audio, str) or len(audio) > 16 * 1024 * 1024:
            raise ValueError("El archivo no puede superar los 12 MiB.")
        try:
            raw = base64.b64decode(audio, validate=True)
        except ValueError as exc:
            raise ValueError("El audio no tiene una codificación válida.") from exc
        if not raw or len(raw) > 12 * 1024 * 1024:
            raise ValueError("Selecciona un audio de hasta 12 MiB.")
        target.write_bytes(raw)

    def upload(self, data):
        with tempfile.TemporaryDirectory(prefix="voice-") as temporary:
            path = Path(temporary) / "upload.audio"
            self.uploaded_audio(data.get("audio_base64"), path)
            return self.add_file(path, data.get("name"), data.get("transcript"))

    def update(self, voice_id, data):
        if not data or set(data) - {"name", "transcript", "enabled", "audio_base64"}:
            raise ValueError("Envía nombre, transcripción, estado o muestra de audio.")
        if "enabled" in data and not isinstance(data["enabled"], bool):
            raise ValueError("enabled debe ser true o false.")
        with tempfile.TemporaryDirectory(prefix="voice-") as temporary:
            staged = Path(temporary) / "reference.wav"
            seconds = None
            if "audio_base64" in data:
                source = Path(temporary) / "upload.audio"
                self.uploaded_audio(data["audio_base64"], source)
                seconds = self.convert(source, staged)
            with self.lock:
                voice = self.get(voice_id)
                old_reference = Path(voice["reference"])
                voice.update({k: v for k, v in data.items() if k != "audio_base64"})
                validate_details(voice["name"], voice["transcript"])
                self.unique_name(voice["name"], voice_id)
                voice["name"], voice["transcript"] = voice["name"].strip(), voice["transcript"].strip()
                target = None
                if seconds is not None:
                    target = self.directory(voice_id) / f"reference-{uuid.uuid4().hex}.wav"
                    shutil.copyfile(staged, target)
                    voice.update(reference=str(target), duration_seconds=seconds)
                voice["updated_at"] = datetime.now(timezone.utc).isoformat()
                try:
                    atomic_json(self.directory(voice_id) / "voice.json", voice)
                except Exception:
                    if target:
                        target.unlink(missing_ok=True)
                    raise
                if target:
                    old_reference.unlink(missing_ok=True)
                return voice

    def delete(self, voice_id):
        with self.lock:
            voice = self.get(voice_id)
            # A root recording must not silently reappear on the next import.
            atomic_json(VOICES / ".deleted" / f"{voice_id}.json",
                        {"name": voice["name"], "source": voice.get("source")})
            shutil.rmtree(self.directory(voice_id))
            return {"deleted": voice_id, "name": voice["name"]}

    def import_folder(self, restore_deleted=False):
        if not isinstance(restore_deleted, bool):
            raise ValueError("restore_deleted debe ser true o false.")
        imported, errors, skipped_deleted = [], [], 0
        for path in sorted(VOICES.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
                continue
            voice_id = hashlib.sha256(path.name.encode()).hexdigest()[:32]
            with self.lock:
                if (VOICES / "library" / voice_id / "voice.json").is_file():
                    continue
                if not restore_deleted and (VOICES / ".deleted" / f"{voice_id}.json").exists():
                    skipped_deleted += 1
                    continue
                transcript_path = path.with_suffix(".txt")
                if transcript_path.is_symlink() or not transcript_path.is_file():
                    errors.append(f"Falta {transcript_path.name} para {path.name}")
                    continue
                try:
                    imported.append(self.add_file(path, path.stem, transcript_path.read_text(encoding="utf-8"),
                                                  voice_id=voice_id, source=path.name))
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(f"{path.name}: {exc}")
        return {"imported": imported, "errors": errors, "skipped_deleted": skipped_deleted}
