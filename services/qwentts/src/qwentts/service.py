"""Persistent serial queue, shared inference slot and disposable model processes."""

from contextlib import contextmanager
import errno
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from qwentts.config import DATA, LANGUAGES, LOCK, MODEL, model_ready
from qwentts.store import Store
from qwentts.voices import Voices


def oom_kills():
    try:
        events = dict(line.split() for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines())
        return int(events["oom_kill"])
    except (OSError, ValueError, KeyError):
        return None


class Service:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "jobs").mkdir(exist_ok=True)
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        self.store = Store(DATA)
        self.voices = Voices()
        self.control = threading.RLock()
        self.stopping = threading.Event()
        self.cancelled = threading.Event()
        self.active_id = None
        self.process = None
        self.thread = threading.Thread(target=self.run, name="tts-queue", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.cancelled.set()
        self.terminate()
        self.thread.join(timeout=12)

    def directory(self, job_id):
        if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Identificador de trabajo no válido.")
        return DATA / "jobs" / job_id

    def job(self, job_id):
        job = self.store.get(job_id)
        if not job:
            raise ValueError("No se encuentra ese trabajo.")
        progress = self.directory(job_id) / "progress.json"
        if progress.is_file():
            try:
                job["progress"] = json.loads(progress.read_text())
            except (ValueError, OSError):
                pass
        if job["status"] == "ready":
            job["mp3_url"] = f"/api/jobs/{job_id}/audio.mp3"
            job["wav_url"] = f"/api/jobs/{job_id}/audio.wav"
        return job

    def enqueue(self, data):
        request_key = data.get("request_key")
        if request_key is not None:
            if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
                raise ValueError("request_key debe tener entre 1 y 128 caracteres.")
            existing = self.store.by_request_key(request_key)
            if existing:
                return self.job(existing["id"])
        if not model_ready():
            raise ValueError("El modelo aún no está descargado. Consulta las instrucciones de instalación.")
        text = data.get("text")
        if not isinstance(text, str) or not 5 <= len(text.strip()) <= 5000:
            raise ValueError("Escribe un texto de entre 5 y 5.000 caracteres.")
        language = data.get("language", "Spanish")
        if language not in LANGUAGES:
            raise ValueError("El idioma seleccionado no está disponible.")
        # Library changes and the job's independent reference snapshot are atomic
        # with respect to each other. Workers never read from the live library.
        with self.control, self.voices.lock:
            if request_key:
                existing = self.store.by_request_key(request_key)
                if existing:
                    return self.job(existing["id"])
            voice = self.voices.get(data.get("voice_id"))
            if not voice["enabled"]:
                raise ValueError("Esta voz está desactivada. Actívala antes de generar una locución.")
            request = {"text": text.strip(), "language": language, "voice": voice, "seed": 42}
            job = self.store.create(request, request_key=request_key)
            try:
                directory = self.directory(job["id"])
                directory.mkdir()
                shutil.copyfile(voice["reference"], directory / "reference.wav")
                (directory / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2))
                self.store.update(job["id"], "queued")
            except Exception:
                self.store.update(job["id"], "error", error="No se pudo preparar el trabajo en disco.")
                raise
        return self.job(job["id"])

    def cancel(self, job_id):
        with self.control:
            job = self.job(job_id)
            if job["status"] in {"ready", "error", "cancelled"}:
                return job
            if self.active_id == job_id:
                self.cancelled.set()
                self.terminate()
            self.store.update(job_id, "cancelled", error="Cancelado por el usuario.")
            return self.job(job_id)

    def purge_news(self, story_id):
        """Retire only terminal attempts owned by one orchestrated news story.

        Keep the row/request_key as a tombstone for idempotency. Never touch
        manual jobs, pending inference, the voice library or model weights.
        """
        if (not isinstance(story_id, str) or len(story_id) != 64
                or any(c not in "0123456789abcdef" for c in story_id)):
            raise ValueError("Identificador de noticia no válido.")
        count, pending = 0, []
        with self.control:
            for job in self.store.by_request_prefix(f"orch:{story_id}:tts:"):
                if job["id"] == self.active_id or job["status"] not in {"ready", "error", "cancelled", "purged"}:
                    pending.append(job["id"])
                    continue
                directory = self.directory(job["id"])
                if directory.is_symlink():
                    raise ValueError("La carpeta de audio contiene un enlace inesperado.")
                existed = directory.exists()
                if job["status"] != "purged":
                    self.store.update(job["id"], "purged", result=job["result"], error=job["error"])
                if existed:
                    shutil.rmtree(directory)
                if existed or job["status"] != "purged":
                    count += 1
        return {"purged_count": count, "pending": pending}

    def terminate(self):
        process = self.process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def run(self):
        while not self.stopping.wait(0.5):
            with self.control:
                job = self.store.next()
                if job:
                    self.active_id = job["id"]
                    self.cancelled.clear()
                    self.store.update(job["id"], "waiting")
            if not job:
                continue
            try:
                self.run_job(job)
            except Exception as exc:
                logging.exception("TTS job failed")
                if not self.cancelled.is_set():
                    self.store.update(job["id"], "error", error=str(exc)[:1500])
            finally:
                with self.control:
                    self.active_id = None
                    self.process = None

    @contextmanager
    def slot(self):
        with LOCK.open("a+") as lock:
            acquired = False
            try:
                while not self.cancelled.is_set() and not self.stopping.is_set():
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        self.cancelled.wait(1)
                yield acquired
            finally:
                if acquired:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def unload_ollama():
        url = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
        try:
            with urlopen(url + "/api/ps", timeout=8) as response:
                models = json.load(response).get("models", [])
        except URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError) or getattr(exc.reason, "errno", None) == errno.ECONNREFUSED:
                return  # No running Ollama server can hold a resident model.
            raise RuntimeError("No se pudo comprobar la memoria de Ollama. Se aplaza Qwen para evitar solapar modelos.") from exc
        for model in models:
            name = model.get("name") or model.get("model")
            request = Request(url + "/api/generate", data=json.dumps({"model": name, "keep_alive": 0, "stream": False}).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=60) as response:
                result = json.load(response)
                if result.get("error"):
                    raise RuntimeError("Ollama no pudo liberar su modelo: " + str(result["error"]))
        with urlopen(url + "/api/ps", timeout=8) as response:
            if json.load(response).get("models"):
                raise RuntimeError("Ollama sigue teniendo modelos cargados. Espera a que termine la otra consulta.")

    def run_job(self, job):
        job_id = job["id"]
        directory = self.directory(job_id)
        with self.slot() as acquired:
            if not acquired or self.cancelled.is_set():
                return
            self.unload_ollama()
            if self.cancelled.is_set() or self.stopping.is_set():
                return
            self.store.update(job_id, "running")
            timeout = max(60, int(os.environ.get("QWEN_JOB_TIMEOUT", "1800")))
            started = time.monotonic()
            initial_oom_kills = oom_kills()
            with (directory / "worker.log").open("w") as log:
                process = subprocess.Popen([sys.executable, "-m", "qwentts.worker", str(directory)], stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True,
                                           env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
                with self.control:
                    self.process = process
                    if self.cancelled.is_set():
                        self.terminate()
                try:
                    while process.poll() is None:
                        if self.cancelled.is_set() or self.stopping.is_set():
                            self.terminate()
                            break
                        if time.monotonic() - started > timeout:
                            raise RuntimeError(f"Se ha superado el límite de {timeout // 60} minutos de generación. Reduce el texto o revisa el rendimiento.")
                        self.cancelled.wait(0.5)
                finally:
                    if process.poll() is None:
                        self.terminate()
                        try:
                            process.wait(timeout=8)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                if self.cancelled.is_set() or self.stopping.is_set():
                    self.store.update(job_id, "cancelled", error="La generación se ha detenido.")
                    return
                if process.returncode:
                    final_oom_kills = oom_kills()
                    if (initial_oom_kills is not None and final_oom_kills is not None
                            and final_oom_kills > initial_oom_kills):
                        raise RuntimeError("Qwen superó el límite de memoria del contenedor al generar un fragmento. "
                                           "Consulta progress.json y worker.log; no se ha publicado audio incompleto.")
                    if process.returncode in {-9, 137}:
                        raise RuntimeError("El proceso de síntesis fue terminado por una señal externa. "
                                           "No se ha podido confirmar falta de memoria; consulta worker.log.")
                    tail = (directory / "worker.log").read_text(errors="replace")[-1800:]
                    raise RuntimeError("Qwen no pudo terminar la locución. Detalle: " + tail)
            result = json.loads((directory / "result.json").read_text())
            self.store.update(job_id, "ready", result=result)
        # The inference slot is released only after the model process has exited.

    def status(self):
        def read_number(path):
            try:
                return round(int(Path(path).read_text()) / 1024 / 1024, 1)
            except (OSError, ValueError):
                return None
        with LOCK.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
                occupied = False
            except BlockingIOError:
                occupied = True
        return {"model_ready": model_ready(), "model": os.environ.get("QWEN_MODEL_ID"),
                "dtype": os.environ.get("QWEN_DTYPE", "float32"), "device": "cpu",
                "threads": int(os.environ.get("QWEN_THREADS", "2")), "active_id": self.active_id,
                "chunk_mode": os.environ.get("QWEN_CHUNK_MODE", "sentences"),
                "inference_busy": occupied, "memory_mib": read_number("/sys/fs/cgroup/memory.current"),
                "memory_limit_mib": read_number("/sys/fs/cgroup/memory.max"),
                "languages": LANGUAGES, "jobs": self.store.list()}
