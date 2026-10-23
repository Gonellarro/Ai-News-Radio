"""Lightweight coordinator: serial disposable model workers, then one WAV/MP3."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

from qwentts.progress import Progress
from qwentts.text import split_text


def join_chunks(paths, destination, pause_ms):
    """Copy PCM in bounded buffers; encode MP3 once, after every fragment."""
    temporary = destination.with_name("output.tmp.wav")
    sample_rate, frames, signature = None, 0, None
    with wave.open(str(temporary), "wb") as output:
        for index, path in enumerate(paths):
            with wave.open(str(path), "rb") as source:
                current = (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype())
                if current[0:2] != (1, 2) or current[3] != "NONE" or source.getnframes() == 0:
                    raise RuntimeError("Un fragmento no contiene audio PCM mono de 16 bits válido.")
                if signature is None:
                    signature = current
                    sample_rate = current[2]
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(sample_rate)
                elif current != signature:
                    raise RuntimeError("Los fragmentos no tienen el mismo formato de audio.")
                if index:
                    pause_frames = round(sample_rate * pause_ms / 1000)
                    output.writeframesraw(b"\x00\x00" * pause_frames)
                    frames += pause_frames
                while audio := source.readframes(65536):
                    output.writeframesraw(audio)
                    frames += len(audio) // 2
    temporary.replace(destination)
    return sample_rate, frames


def main():
    directory = Path(sys.argv[1])
    request = json.loads((directory / "request.json").read_text())
    started = time.monotonic()

    progress = Progress(directory, started)
    mode = os.environ.get("QWEN_CHUNK_MODE", "sentences")
    target = max(80, min(1000, int(os.environ.get("QWEN_CHUNK_CHARS", "160"))))
    pause_ms = max(0, min(1000, int(os.environ.get("QWEN_CHUNK_PAUSE_MS", "160"))))
    chunks = split_text(request["text"], target, mode)
    if not chunks:
        raise ValueError("No hay texto que locutar.")
    (directory / "chunks.json").write_text(json.dumps({"version": 1, "mode": mode, "target_characters": target,
                                                        "pause_ms": pause_ms, "chunks": chunks},
                                                       ensure_ascii=False, indent=2))
    progress("splitting", total_chunks=len(chunks), message=f"Texto organizado en {len(chunks)} fragmentos completos")
    details, paths = [], []
    for index in range(len(chunks)):
        # Inherit the coordinator's process group: cancellation kills the active
        # model too. Wait for its exit before starting another, freeing its RAM.
        result = subprocess.run([sys.executable, "-m", "qwentts.chunk_worker", str(directory), str(index), str(started)],
                                check=False)
        if result.returncode:
            progress("error", chunk=index + 1, total_chunks=len(chunks),
                     message=f"No se pudo completar el fragmento {index + 1}; el audio final no se publicará")
            if result.returncode in {-9, 137}:
                sys.exit(137)  # Preserve SIGKILL diagnosis in the HTTP supervisor.
            raise RuntimeError(f"Qwen falló en el fragmento {index + 1} de {len(chunks)} (código {result.returncode}).")
        chunk_directory = directory / "chunks" / f"{index + 1:04d}"
        details.append(json.loads((chunk_directory / "result.json").read_text()))
        paths.append(chunk_directory / "audio.wav")
    progress("joining", total_chunks=len(chunks), message="Uniendo los fragmentos en una sola locución")
    sample_rate, frames = join_chunks(paths, directory / "output.wav", pause_ms)
    progress("encoding", message="Guardando el MP3 de la locución completa")
    temporary_mp3 = directory / "output.tmp.mp3"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-threads", "1", "-i", str(directory / "output.wav"),
                    "-codec:a", "libmp3lame", "-b:a", "128k", str(temporary_mp3)], check=True, timeout=60)
    temporary_mp3.replace(directory / "output.mp3")
    elapsed = time.monotonic() - started
    result = {"model": os.environ["QWEN_MODEL_ID"], "revision": os.environ["QWEN_MODEL_REVISION"],
              "dtype": os.environ.get("QWEN_DTYPE", "float32"), "sample_rate": sample_rate,
              "audio_seconds": round(frames / sample_rate, 2), "elapsed_seconds": round(elapsed, 1),
              "load_seconds": round(sum(item["load_seconds"] for item in details), 1),
              "peak_rss_mib": max(item["peak_rss_mib"] for item in details),
              "real_time_factor": round(elapsed / (frames / sample_rate), 2), "chunks": len(chunks),
              "chunk_mode": mode, "chunk_details": details}
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    progress("done", message="Locución completa; todos los fragmentos unidos", **result)


if __name__ == "__main__":
    main()
