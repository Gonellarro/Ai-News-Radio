"""Private YouTube credentials and process-independent start/stop requests."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from news_orchestrator import config

DIRECTORY = config.DATA / "youtube"
SERVER = "rtmps://a.rtmps.youtube.com:443/live2"
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{10,200}")


def private_directory():
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    DIRECTORY.chmod(0o700)
    return DIRECTORY


def load():
    try:
        value = json.loads((DIRECTORY / "settings.json").read_text())
    except FileNotFoundError:
        return {"enabled": False, "stream_key": "", "revision": "initial"}
    if (not isinstance(value, dict) or type(value.get("enabled")) is not bool
            or not isinstance(value.get("stream_key"), str)
            or not isinstance(value.get("revision"), str)
            or (value["stream_key"] and not KEY_PATTERN.fullmatch(value["stream_key"]))):
        raise ValueError("La configuración privada de YouTube no es válida.")
    return value


@contextmanager
def locked():
    private_directory()
    descriptor = os.open(DIRECTORY / "settings.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def save(value):
    value = {**value, "revision": uuid.uuid4().hex}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=private_directory(), prefix=".settings-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(DIRECTORY / "settings.json")
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def age(value):
    try:
        return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds())
    except (ValueError, TypeError):
        return float("inf")


def worker_status():
    try:
        value = json.loads((DIRECTORY / "status.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def redact(text, key=""):
    if key:
        text = text.replace(key, "<clave oculta>")
    return re.sub(r"rtmps?://[^\s\"'\]]+", "<destino YouTube>", text)


def public_status():
    settings = load()
    worker = worker_status()
    online = age(worker.get("updated_at")) < 15
    state = worker.get("state", "stopped")
    if not online:
        state = "unavailable"
    elif settings["revision"] != worker.get("revision"):
        state = "starting" if settings["enabled"] else "stopping"
    return {"enabled": settings["enabled"], "configured": bool(settings["stream_key"]),
            "server": SERVER, "worker_online": online, "state": state,
            "error": redact(str(worker.get("error", "")), settings["stream_key"])[:1500],
            **{key: worker.get(key) for key in ("updated_at", "started_at", "last_progress_at", "retry_at",
                                               "reconnects", "sent_bytes", "video_seconds")}}


def update_key(value):
    if not isinstance(value, str) or not KEY_PATTERN.fullmatch(value.strip()):
        raise ValueError("Pega solo la clave de emisión de YouTube, sin URL ni espacios interiores.")
    with locked():
        settings = load()
        if settings["enabled"]:
            raise ValueError("Detén primero la salida a YouTube para cambiar la clave.")
        save({**settings, "stream_key": value.strip()})
    return public_status()


def start():
    with locked():
        settings = load()
        if not settings["stream_key"]:
            raise ValueError("Guarda primero la clave de emisión de YouTube.")
        if age(worker_status().get("updated_at")) >= 15:
            raise ValueError("El servicio de salida a YouTube no está disponible. Revisa el contenedor youtube.")
        if not settings["enabled"]:
            save({**settings, "enabled": True})
    return public_status()


def stop():
    with locked():
        settings = load()
        if settings["enabled"]:
            save({**settings, "enabled": False})
    return public_status()


def logs():
    try:
        with (DIRECTORY / "relay.log").open("rb") as handle:
            handle.seek(max(0, (DIRECTORY / "relay.log").stat().st_size - 12000))
            text = handle.read(12000).decode(errors="replace")
    except FileNotFoundError:
        text = "Todavía no hay incidencias de la salida a YouTube."
    return redact(text, load()["stream_key"])
