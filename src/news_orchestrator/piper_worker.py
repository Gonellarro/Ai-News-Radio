"""Disposable Piper inference process: one voice load, one narration, then exit."""

import json
from pathlib import Path
import resource
import sys
import time
import wave

from news_orchestrator import config, piper_assets


def main():
    started = time.monotonic()
    directory = Path(sys.argv[1])
    request = json.loads((directory / "narration-request.json").read_text())
    selected = piper_assets.voice(request["voice_id"], require_ready=True, verify=True)

    # Imported only by the child. The API, broadcaster and scheduler stay light.
    import onnxruntime
    from piper import PiperVoice, SynthesisConfig
    from piper.config import PiperConfig

    folder = piper_assets.directory(selected["id"])
    model_config = json.loads((folder / selected["files"]["config"]["name"]).read_text())
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    voice = PiperVoice(config=PiperConfig.from_dict(model_config), session=onnxruntime.InferenceSession(
        str(folder / selected["files"]["model"]["name"]), sess_options=options,
        providers=["CPUExecutionProvider"]))
    loaded = time.monotonic()
    temporary = directory / "narration.part.wav"
    try:
        with wave.open(str(temporary), "wb") as output:
            voice.synthesize_wav(request["text"], output, syn_config=SynthesisConfig(normalize_audio=False))
        with wave.open(str(temporary), "rb") as audio:
            if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or not audio.getnframes():
                raise RuntimeError("Piper no produjo audio PCM mono válido.")
            seconds = audio.getnframes() / audio.getframerate()
            sample_rate = audio.getframerate()
        elapsed = time.monotonic() - started
        temporary.replace(directory / "narration.wav")
        config.atomic_json(directory / "narration.json", {
            "engine": "piper", "voice_id": selected["id"], "voice_name": selected["name"],
            "revision": selected["revision"], "model_sha256": selected["files"]["model"]["sha256"],
            "text_sha256": request["text_sha256"], "audio_seconds": round(seconds, 2),
            "elapsed_seconds": round(elapsed, 2), "load_seconds": round(loaded - started, 2),
            "sample_rate": sample_rate, "real_time_factor": round(elapsed / seconds, 3),
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)})
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
