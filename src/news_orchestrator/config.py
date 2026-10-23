import json
import math
import os
from pathlib import Path
import threading
import hashlib

from news_orchestrator import balancing, relevance_policy, scheduling

DATA = Path(os.environ.get("DATA_DIR", "/app/data"))
CONFIG = Path(os.environ.get("CONFIG_DIR", "/app/config"))
WEB = Path(os.environ.get("WEB_DIR", "/app/web"))
WRITE_LOCK = threading.Lock()


def load():
    value = json.loads((CONFIG / "channel.json").read_text())
    return validate(value)


def validate(value):
    if not isinstance(value, dict) or not isinstance(value.get("enabled"), bool):
        raise ValueError("channel.json debe contener enabled: true o false.")
    for key in ["channel_name", "topic", "voice_name", "tts_language"]:
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 200:
            raise ValueError(f"{key} debe ser un texto de entre 1 y 200 caracteres.")
    value.setdefault("voice_mode", "fixed")
    # Preserve the previous value as the size of each scheduled batch.
    value.setdefault("new_stories_per_update", value.pop("new_stories_per_hour", 5))
    value.setdefault("schedule_timezone", scheduling.DEFAULT_ZONE)
    scheduling.validate(value.get("scan_interval_seconds"), value["schedule_timezone"])
    value.setdefault("qwen_voice_id", "")
    voice_id = value["qwen_voice_id"]
    if not isinstance(voice_id, str) or (voice_id and (len(voice_id) != 32 or any(c not in "0123456789abcdef" for c in voice_id))):
        raise ValueError("qwen_voice_id debe ser el identificador de una voz de Qwen o un texto vacío.")
    value.setdefault("tts_engine", "qwen")
    value.setdefault("piper_voice", "es_ES-davefx-medium")
    if not isinstance(value["tts_engine"], str) or value["tts_engine"] not in {"qwen", "piper"}:
        raise ValueError("tts_engine debe ser qwen o piper.")
    if not isinstance(value["piper_voice"], str):
        raise ValueError("piper_voice debe ser un identificador de voz.")
    from news_orchestrator.piper_assets import voice
    selected = voice(value["piper_voice"])
    if value["tts_engine"] == "piper" and selected["language"] != value["tts_language"]:
        raise ValueError("El idioma de la voz Piper debe coincidir con tts_language.")
    value["balancing"] = balancing.validate(value.get("balancing", {"strategy": "fair", "weights": {}}))
    value["relevance"] = relevance_policy.validate(value.get("relevance", {}))
    value.setdefault("voice_names", [])
    value.setdefault("voice_exclude", ["qwen-demo-en"])
    value.setdefault("audio_intro_seconds", 1.0)
    value.setdefault("audio_outro_seconds", 2.0)
    value.setdefault("intro_music_enabled", False)
    value.setdefault("voice_normalization_enabled", True)
    value.setdefault("voice_loudness_lufs", -16.0)
    value.setdefault("voice_true_peak_dbtp", -2.0)
    value.setdefault("voice_loudness_range_lu", 7.0)
    if not isinstance(value["voice_normalization_enabled"], bool):
        raise ValueError("voice_normalization_enabled debe ser true o false.")
    for key, low, high in [("voice_loudness_lufs", -30, -12), ("voice_true_peak_dbtp", -9, -1),
                           ("voice_loudness_range_lu", 1, 20)]:
        if type(value[key]) not in {int, float} or not math.isfinite(value[key]) or not low <= value[key] <= high:
            raise ValueError(f"{key} debe ser un número entre {low} y {high}.")
    if not isinstance(value["intro_music_enabled"], bool):
        raise ValueError("intro_music_enabled debe ser true o false.")
    for key in ["audio_intro_seconds", "audio_outro_seconds"]:
        if type(value[key]) not in {int, float} or not math.isfinite(value[key]) or not 0 <= value[key] <= 10:
            raise ValueError(f"{key} debe ser un número entre 0 y 10 segundos.")
    if not isinstance(value["voice_mode"], str) or value["voice_mode"] not in {"fixed", "random"}:
        raise ValueError("voice_mode debe ser fixed o random.")
    for key in ["voice_names", "voice_exclude"]:
        if not isinstance(value[key], list) or any(not isinstance(v, str) or not v.strip() for v in value[key]):
            raise ValueError(f"{key} debe ser una lista de nombres de voz.")
    # Older configurations used a days-long archive. Retirement now removes
    # generated files automatically once playback no longer needs them.
    value.pop("artifact_retention_days", None)
    for key in ("max_playlist", "max_pending", "new_stories_per_update"):
        if type(value.get(key)) is not int or value[key] < 1:
            raise ValueError(f"{key} debe ser un entero positivo.")
    for key, low, high in [("max_age_hours", 1, 168)]:
        if type(value.get(key)) is not int or not low <= value[key] <= high:
            raise ValueError(f"{key} debe estar entre {low} y {high}.")
    if not isinstance(value.get("platform"), str) or value["platform"] not in {"web", "all", "social", "reddit", "mastodon", "bluesky"}:
        raise ValueError("La plataforma no es válida.")
    if not isinstance(value.get("language"), str) or value["language"] not in {"all", "en", "es"}:
        raise ValueError("El idioma de las fuentes no es válido.")
    if value["tts_language"] not in {"Spanish", "English", "French", "German", "Italian", "Portuguese", "Chinese", "Japanese", "Korean", "Russian"}:
        raise ValueError("El idioma de locución no está disponible en Qwen.")
    if not isinstance(value.get("query", ""), str) or len(value.get("query", "")) > 300:
        raise ValueError("query debe ser un texto de hasta 300 caracteres.")
    if not isinstance(value.get("source_ids"), list) or any(not isinstance(s, str) for s in value["source_ids"]):
        raise ValueError("source_ids debe ser una lista de identificadores de fuente.")
    return value


def save_narration(payload):
    required = {"tts_engine", "piper_voice"}
    if not required <= set(payload) or set(payload) - required - {"voice_mode", "qwen_voice_id"}:
        raise ValueError("Envía motor, voz Piper y, opcionalmente, modo y voz de Qwen.")
    with WRITE_LOCK:
        value = json.loads((CONFIG / "channel.json").read_text())
        value.update(payload)
        validated = validate(value)
        if validated["tts_engine"] == "piper":
            from news_orchestrator.piper_assets import voice
            if not voice(validated["piper_voice"])["ready"]:
                raise ValueError("Descarga la voz de Piper antes de seleccionarla.")
        atomic_json(CONFIG / "channel.json", validated)
    return {key: validated[key] for key in ("tts_engine", "piper_voice", "voice_mode", "qwen_voice_id")}


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot():
    value = load()
    return {"settings": value, "revision": revision(value), "schedule": scheduling.public(value)}


def update(payload, store):
    """Partial, validated configuration edits; reject stale browser forms."""
    if set(payload) != {"revision", "changes"} or not isinstance(payload["changes"], dict):
        raise ValueError("Envía revision y changes para guardar la configuración.")
    with WRITE_LOCK:
        current = load()
        if payload["revision"] != revision(current):
            raise ValueError("La configuración ha cambiado. Recarga los valores antes de guardar.")
        if set(payload["changes"]) - set(current):
            raise ValueError("La configuración contiene campos desconocidos.")
        value = validate({**current, **payload["changes"]})
        if value["tts_engine"] == "piper":
            from news_orchestrator.piper_assets import voice
            if not voice(value["piper_voice"])["ready"]:
                raise ValueError("La voz Piper seleccionada no está descargada.")
        selection_keys = {"max_playlist", "max_pending", "max_age_hours", "tts_engine",
                          "balancing", "relevance", "topic"}
        written = False
        try:
            # Reuse the initialized store; never run schema migrations on save.
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                pinned = db.execute("SELECT COUNT(*) FROM jobs WHERE active=1 AND pinned=1").fetchone()[0]
                if value["max_playlist"] < pinned:
                    raise ValueError(f"Hay {pinned} noticias fijadas. Desfíjalas antes de reducir la parrilla.")
                if any(current[key] != value[key] for key in selection_keys):
                    store._trim(db, value)
                atomic_json(CONFIG / "channel.json", value)
                written = True
        except Exception:
            # Do not leave the file saved if the database transaction fails.
            if written:
                atomic_json(CONFIG / "channel.json", current)
            raise
    return {"settings": value, "revision": revision(value), "schedule": scheduling.public(value)}


def editorial():
    value = (CONFIG / "editorial.md").read_text().strip()
    if not 1 <= len(value) <= 6000:
        raise ValueError("editorial.md debe tener entre 1 y 6.000 caracteres.")
    return value


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)
