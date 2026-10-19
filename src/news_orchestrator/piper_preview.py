"""Create a short Davefx listening sample without starting news production."""

import json
import threading

from news_orchestrator import config, loudness, media
from news_orchestrator.narration import PiperProvider

TEXT = ("Esta es una muestra de la voz Davefx, en español. El canal prepara noticias de "
        "inteligencia artificial y cita su fuente al terminar cada información. "
        "Puedes comparar esta voz con las locuciones anteriores y elegir el motor que prefieras.")


def main():
    settings = {**config.load(), "tts_engine": "piper", "piper_voice": "es_ES-davefx-medium"}
    directory = config.DATA / "previews" / "davefx"
    directory.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    work = {"tts_engine": "piper", "script": TEXT}
    provider = PiperProvider()
    provider.ready(settings)
    provider.generate("preview", work, settings, directory, stop, lambda stage: None, None)
    source = directory / "narration.wav"
    normalization = loudness.profile(settings)
    if normalization:
        normalized = directory / "normalized.wav"
        loudness.normalize(source, normalized, normalization, stop)
        source = normalized
    destination = directory.parent / "piper-davefx.mp3"
    temporary = destination.with_name("piper-davefx.part.mp3")
    try:
        media.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1", "-i", str(source),
                   "-c:a", "libmp3lame", "-b:a", "128k", str(temporary)], directory / "mp3.log", stop)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"sample": str(destination), "metrics": work["tts_metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
