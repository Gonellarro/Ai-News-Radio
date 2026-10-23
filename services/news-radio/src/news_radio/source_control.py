"""Validated, atomic source catalog editing owned by the collector service."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from news_radio.catalog import load_sources

LOCK = threading.Lock()


def path():
    return Path(os.environ.get("NEWS_RADIO_CONFIG_DIR", Path(__file__).resolve().parents[2] / "config")) / "sources.json"


def snapshot():
    value = json.loads(path().read_text(encoding="utf-8"))
    load_sources(value)
    revision = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return {"catalog": value, "revision": revision}


def update(payload):
    if not isinstance(payload, dict) or set(payload) != {"revision", "catalog"}:
        raise ValueError("Envía el catálogo y su revisión.")
    load_sources(payload["catalog"])
    with LOCK:
        if snapshot()["revision"] != payload["revision"]:
            raise ValueError("El catálogo ha cambiado. Actualízalo antes de guardar.")
        filename = path()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=filename.parent, prefix=".sources-", delete=False, encoding="utf-8") as handle:
                temporary = Path(handle.name)
                json.dump(payload["catalog"], handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(filename)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return snapshot()
