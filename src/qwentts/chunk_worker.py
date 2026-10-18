"""Generate one complete text fragment, save PCM, then release the entire model."""

from functools import partial
import json
import os
from pathlib import Path
import resource
import sys
import time

from qwentts.progress import Progress


def main():
    directory = Path(sys.argv[1])
    index = int(sys.argv[2])
    started = time.monotonic()
    request = json.loads((directory / "request.json").read_text())
    plan = json.loads((directory / "chunks.json").read_text())
    chunk = plan["chunks"][index]
    destination = directory / "chunks" / f"{index + 1:04d}"
    destination.mkdir(parents=True, exist_ok=True)
    progress = Progress(directory, float(sys.argv[3]), chunk=index + 1, total_chunks=len(plan["chunks"]),
                        chunk_chars=len(chunk))
    progress("loading", message=f"Cargando Qwen para el fragmento {index + 1} de {len(plan['chunks'])}")

    # Neither the HTTP service nor the text/audio coordinator imports PyTorch.
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    torch.set_num_threads(max(1, int(os.environ.get("QWEN_THREADS", "2"))))
    torch.set_num_interop_threads(1)
    torch.manual_seed(request.get("seed", 42) + index)
    dtype_name = os.environ.get("QWEN_DTYPE", "float32")
    dtype = {"bfloat16": torch.bfloat16, "float32": torch.float32}.get(dtype_name)
    if dtype is None:
        raise ValueError("QWEN_DTYPE debe ser bfloat16 o float32 para este servicio CPU.")
    model = Qwen3TTSModel.from_pretrained(os.environ["QWEN_MODEL_DIR"], device_map="cpu", dtype=dtype,
                                         attn_implementation="sdpa", local_files_only=True)
    # Qwen's pinned 12Hz decoder already supports blocks with left context.
    # Keep its original context and concatenation, reducing the 300-frame window.
    decode_frames = max(32, min(300, int(os.environ.get("QWEN_DECODE_CHUNK_FRAMES", "64"))))
    decoder = model.model.speech_tokenizer.model.decoder
    decoder.chunked_decode = partial(decoder.chunked_decode, chunk_size=decode_frames)
    loaded = time.monotonic()
    progress("cloning", message=f"Preparando la voz para el fragmento {index + 1}")
    prompt = model.create_voice_clone_prompt(ref_audio=str(directory / "reference.wav"),
                                             ref_text=request["voice"]["transcript"], x_vector_only_mode=False)
    progress("generating", message=f"Locutando fragmento {index + 1} de {len(plan['chunks'])}")
    with torch.inference_mode():
        waves, rate = model.generate_voice_clone(text=chunk, language=request["language"], voice_clone_prompt=prompt,
                                                 max_new_tokens=1024, non_streaming_mode=True)
    audio = np.asarray(waves[0], dtype=np.float32)
    if not len(audio) or not np.isfinite(audio).all():
        raise RuntimeError("Qwen produjo un fragmento de audio vacío o no válido.")
    if len(audio) / rate >= 82:
        raise RuntimeError("El fragmento alcanzó el límite de generación; no se publicará una locución posiblemente cortada.")
    temporary = destination / "audio.tmp.wav"
    sf.write(temporary, audio, rate, subtype="PCM_16")
    temporary.replace(destination / "audio.wav")
    result = {"sample_rate": rate, "audio_seconds": round(len(audio) / rate, 2),
              "elapsed_seconds": round(time.monotonic() - started, 1), "load_seconds": round(loaded - started, 1),
              "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
              "decode_chunk_frames": decode_frames, "characters": len(chunk)}
    (destination / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    progress("releasing", message=f"Fragmento {index + 1} guardado; liberando el modelo")


if __name__ == "__main__":
    main()
