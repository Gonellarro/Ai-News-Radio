"""Narration backends. Qwen keeps its remote queue; Piper runs locally on demand."""

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from news_orchestrator import config, piper_assets, voices as voice_selection
from news_orchestrator.client import RemoteError


def engine(work, settings=None):
    # Saved voice work belongs to its original engine. Legacy work is Qwen.
    if work.get("tts_engine"):
        return work["tts_engine"]
    if work.get("tts_id") or work.get("voice_id"):
        return "qwen"
    return (settings or {}).get("tts_engine", "qwen")


class QwenProvider:
    def __init__(self, client, store):
        self.client, self.store = client, store

    def ready(self, settings):
        if not self.client.request("/api/status", timeout=5).get("model_ready"):
            raise RuntimeError("El modelo de Qwen aún no está disponible.")

    def generate(self, job_id, work, settings, directory, stop, step, wait_remote):
        if not work.get("tts_id"):
            voices = self.client.request("/api/voices")["voices"]
            if work.get("voice_id") and not any(v["id"] == work["voice_id"] and v.get("enabled", True) for v in voices):
                # No remote job exists yet: choose again if the live library
                # changed. Once enqueued, Qwen keeps an independent snapshot.
                work.pop("voice_id", None)
            if not work.get("voice_id"):
                choice = {**settings, "voice_mode": work.get("voice_mode", settings["voice_mode"])}
                if choice["voice_mode"] == "fixed":
                    choice["voice_name"] = work["voice_name"]
                    choice["qwen_voice_id"] = work.get("qwen_voice_id", settings.get("qwen_voice_id", ""))
                voice = voice_selection.choose(voices, choice, self.store.state("last_voice_id"))
                work.update({"voice_id": voice["id"], "voice_name": voice["name"]})
                step("voicing")
                self.store.set_state("last_voice_id", voice["id"])
            if not any(voice["id"] == work["voice_id"] for voice in voices):
                raise RuntimeError(f"La voz '{work['voice_name']}' no está importada en Qwen TTS.")
            value = self.client.request("/api/jobs", {"text": work["script"], "voice_id": work["voice_id"],
                "language": work["tts_language"], "request_key": f"orch:{job_id}:tts:{work.get('tts_generation', 0)}"})
            work["tts_id"] = value["id"]
            step("voicing")
        tts = wait_remote(self.client, f"/api/jobs/{work['tts_id']}",
                          {"preparing", "queued", "waiting", "running"}, 10800)
        if tts["status"] != "ready":
            work.pop("tts_id", None)
            work["tts_generation"] = work.get("tts_generation", 0) + 1
            step("voicing")
            raise RuntimeError(tts.get("error") or "Qwen no pudo terminar el audio.")
        work["tts_metrics"] = tts["result"]
        step("downloading")

    def source(self, work, directory, target):
        self.client.download(f"/api/jobs/{work['tts_id']}/audio.wav", target)


class PiperProvider:
    def ready(self, settings):
        piper_assets.voice(settings["piper_voice"], require_ready=True)
        if importlib.util.find_spec("piper") is None:
            raise RuntimeError("Piper no está instalado en la imagen. Reconstruye el contenedor del orquestador.")

    def generate(self, job_id, work, settings, directory, stop, step, wait_remote):
        if not work.get("piper_voice"):
            selected = piper_assets.voice(settings["piper_voice"], require_ready=True)
            work.update({"piper_voice": selected["id"], "voice_name": selected["name"]})
            step("voicing")
        selected = piper_assets.voice(work["piper_voice"], require_ready=True)
        text_hash = hashlib.sha256(work["script"].encode()).hexdigest()
        try:
            saved = json.loads((directory / "narration.json").read_text())
        except (OSError, ValueError):
            saved = {}
        if not (saved.get("text_sha256") == text_hash and saved.get("voice_id") == selected["id"]
                and saved.get("model_sha256") == selected["files"]["model"]["sha256"]
                and (directory / "narration.wav").is_file()):
            config.atomic_json(directory / "narration-request.json", {
                "text": work["script"], "text_sha256": text_hash, "voice_id": selected["id"]})
            lock_path = Path(os.environ.get("AI_RUNTIME_LOCK", "/run/local-ai/inference.lock"))
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RemoteError("La IA local está ocupada; Piper esperará su turno.", 409) from exc
                self._run(directory, stop)
            saved = json.loads((directory / "narration.json").read_text())
        work["tts_metrics"] = saved
        step("downloading")

    @staticmethod
    def _run(directory, stop):
        log_path = directory / "piper.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "news_orchestrator.piper_worker", str(directory)],
                                       stdout=log, stderr=subprocess.STDOUT)
            started = time.monotonic()
            try:
                while process.poll() is None:
                    if stop.wait(0.2):
                        raise InterruptedError("Locución Piper detenida; el trabajo se conserva.")
                    if time.monotonic() - started > 180:
                        raise RuntimeError("Piper superó los tres minutos de generación.")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            if process.returncode:
                raise RuntimeError("Piper no pudo generar la voz: " + log_path.read_text(errors="replace")[-1500:])

    def source(self, work, directory, target):
        original = directory / "narration.wav"
        if not original.is_file() or original.is_symlink():
            raise RuntimeError("No se encuentra el WAV original de Piper de esta noticia.")
        shutil.copyfile(original, target)


class Narration:
    def __init__(self, client, store):
        self.providers = {"qwen": QwenProvider(client, store), "piper": PiperProvider()}

    def ready(self, settings):
        self.providers[settings["tts_engine"]].ready(settings)

    def generate(self, job_id, work, settings, directory, stop, step, wait_remote):
        self.providers[engine(work, settings)].generate(job_id, work, settings, directory, stop, step, wait_remote)

    def source(self, work, directory, target):
        self.providers[engine(work)].source(work, directory, target)
