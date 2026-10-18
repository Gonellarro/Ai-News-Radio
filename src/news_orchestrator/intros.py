"""Choose a local intro once and snapshot it beside the story's media."""

import hashlib
import json
import logging
import math
from pathlib import Path
import secrets
import shutil

from news_orchestrator import config, media


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(65536):
            value.update(chunk)
    return value.hexdigest()


def select(directory, enabled, previous=None):
    directory = Path(directory)
    selection = directory / "intro-selection.json"
    if selection.is_file():
        return json.loads(selection.read_text())["intro"]
    chosen = None
    if enabled:
        library = config.DATA / "intros"
        library.mkdir(parents=True, exist_ok=True)
        files = [p for p in library.iterdir() if p.is_file() and not p.is_symlink()
                 and p.suffix.casefold() == ".mp3" and 0 < p.stat().st_size <= 20 * 1024 * 1024]
        alternatives = [p for p in files if p.name != previous]
        repeats = [p for p in files if p.name == previous]
        random = secrets.SystemRandom()
        random.shuffle(alternatives)
        random.shuffle(repeats)
        for source in alternatives + repeats:
            temporary = directory / "intro.part.mp3"
            try:
                shutil.copyfile(source, temporary)
                info = media.probe(temporary)
                duration = float(info["format"]["duration"])
                if not math.isfinite(duration) or not 0 < duration <= 60:
                    raise ValueError("La intro debe durar entre 0 y 60 segundos.")
                if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
                    raise ValueError("La intro no contiene una pista de audio.")
                chosen = {"name": source.name, "sha256": digest(temporary), "duration_seconds": round(duration, 3)}
                temporary.replace(directory / "intro.mp3")
                break
            except (OSError, ValueError, RuntimeError) as exc:
                logging.warning("Intro %s no utilizable: %s", source.name, exc)
                temporary.unlink(missing_ok=True)
        if chosen is None:
            logging.warning("No hay intros MP3 utilizables en %s; la noticia conservará sus pausas sin música.", library)
    config.atomic_json(selection, {"intro": chosen})
    return chosen
