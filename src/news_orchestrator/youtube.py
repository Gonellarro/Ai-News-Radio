"""Supervise one lightweight HLS to RTMPS relay, independently of production."""

from collections import deque
from datetime import datetime, timedelta, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import subprocess
import threading
import time

from news_orchestrator import config, youtube_control as control

SOURCE = "http://127.0.0.1:8792/live/index.m3u8"


def now():
    return datetime.now(timezone.utc).isoformat()


def command(key):
    # Do not preserve the per-clip timestamps: FFmpeg corrects HLS discontinuities
    # before remuxing. Copy compressed packets, without video/audio inference or encoding.
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning", "-nostats",
            "-stats_period", "1", "-progress", "pipe:1", "-threads", "1",
            "-fflags", "+genpts+discardcorrupt", "-dts_delta_threshold", "1",
            "-rw_timeout", "15000000", "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5", "-live_start_index", "-3", "-seg_max_retry", "2",
            "-re", "-i", SOURCE, "-map", "0:v:0", "-map", "0:a:0", "-sn", "-dn",
            "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
            "-avoid_negative_ts", "make_zero", "-max_muxing_queue_size", "256",
            "-rw_timeout", "15000000", "-tls_verify", "1", "-verifyhost", "a.rtmps.youtube.com",
            "-ca_file", "/etc/ssl/certs/ca-certificates.crt", "-f", "flv", "-flvflags", "no_duration_filesize",
            control.SERVER + "/" + key]


class Relay:
    def __init__(self):
        directory = control.private_directory()
        self.owner = (directory / "relay.lock").open("a")
        fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.stop = threading.Event()
        self.process = None
        self.readers = []
        self.lock = threading.Lock()
        self.progress = {}
        self.errors = deque(maxlen=20)
        self.timestamp_warnings = deque(maxlen=20)
        self.key = ""
        self.revision = ""
        self.reconnects = 0
        self.failures = 0
        self.retry_tick = 0
        self.retry_at = ""
        self.started_at = ""
        self.spawn_tick = 0
        self.progress_tick = 0
        self.last_progress_at = ""
        self.last_time = -1
        self.last_error = ""
        self.logger = logging.getLogger("youtube-relay")
        self.logger.propagate = False
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(directory / "relay.log", maxBytes=1024 * 1024, backupCount=2)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)

    def heartbeat(self, state, error=""):
        with self.lock:
            progress = dict(self.progress)
        value = {"updated_at": now(), "state": state, "revision": self.revision,
                 "error": control.redact(error, self.key)[:1500], "started_at": self.started_at,
                 "last_progress_at": self.last_progress_at, "retry_at": self.retry_at,
                 "reconnects": self.reconnects, "sent_bytes": progress.get("total_size"),
                 "video_seconds": progress.get("out_time_us", 0) / 1000000}
        config.atomic_json(control.DIRECTORY / "status.json", value)

    def read_progress(self, process):
        block = {}
        for raw in process.stdout:
            key, separator, value = raw.strip().partition("=")
            if not separator:
                continue
            if key in {"out_time_us", "total_size"}:
                try:
                    block[key] = int(value)
                except ValueError:
                    pass
            elif key == "progress":
                with self.lock:
                    self.progress.update(block)
                block = {}

    def read_errors(self, process):
        for raw in process.stderr:
            line = control.redact(raw.strip(), self.key)[:1500]
            if not line:
                continue
            with self.lock:
                self.errors.append(line)
                if "non-monoton" in line.casefold():
                    self.timestamp_warnings.append(time.monotonic())
            self.logger.warning("%s", line)

    def launch(self, settings):
        self.key = settings["stream_key"]
        with self.lock:
            self.progress = {}
            self.errors.clear()
            self.timestamp_warnings.clear()
        self.last_time = -1
        self.started_at = now()
        self.last_progress_at = ""
        self.spawn_tick = self.progress_tick = time.monotonic()
        self.process = subprocess.Popen(command(self.key), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, bufsize=1, start_new_session=True)
        self.readers = []
        for target in (self.read_progress, self.read_errors):
            thread = threading.Thread(target=target, args=(self.process,), daemon=True)
            thread.start()
            self.readers.append(thread)
        self.logger.info("Iniciada salida RTMPS; vídeo y audio se copian sin recodificar.")

    def terminate(self):
        if self.process and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait()
        for reader in self.readers:
            reader.join(timeout=1)
        if self.process:
            self.process.stdout.close()
            self.process.stderr.close()
        self.process = None
        self.readers = []

    def fail(self, message):
        self.last_error = control.redact(message, self.key)[:1500]
        self.logger.warning("%s", self.last_error)
        self.terminate()
        self.failures += 1
        self.reconnects += 1
        delay = min(60, 5 * 2 ** min(self.failures - 1, 4))
        self.retry_tick = time.monotonic() + delay
        self.retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

    def source_ready(self):
        try:
            broadcast = json.loads((config.DATA / "broadcast.json").read_text())
            return control.age(broadcast.get("updated_at")) < 20 and (config.DATA / "hls" / "index.m3u8").is_file()
        except (OSError, ValueError):
            return False

    def tick(self):
        settings = control.load()
        if settings["revision"] != self.revision:
            self.terminate()
            self.revision = settings["revision"]
            self.failures = 0
            self.retry_tick = 0
            self.retry_at = ""
            self.last_error = ""
            self.started_at = ""
            self.last_progress_at = ""
            with self.lock:
                self.progress = {}
        if not settings["enabled"]:
            self.terminate()
            self.heartbeat("stopped")
            return
        if not settings["stream_key"]:
            self.terminate()
            self.heartbeat("waiting", "Guarda una clave de emisión para enviar la señal a YouTube.")
            return
        if not self.source_ready():
            self.terminate()
            self.heartbeat("waiting", "Esperando a que se recupere la emisión local.")
            return
        if not self.process:
            if time.monotonic() < self.retry_tick:
                self.heartbeat("retrying", self.last_error)
                return
            self.launch(settings)
        if self.process.poll() is not None:
            with self.lock:
                details = " · ".join(list(self.errors)[-3:])
            self.fail("FFmpeg interrumpió la salida a YouTube. " + (details or "Comprueba la conexión y la clave en YouTube Studio."))
            self.heartbeat("retrying", self.last_error)
            return
        with self.lock:
            position = self.progress.get("out_time_us", -1)
            warnings = list(self.timestamp_warnings)
        if position > self.last_time:
            self.last_time = position
            self.progress_tick = time.monotonic()
            if position > 0:
                self.last_progress_at = now()
                self.last_error = ""
                self.retry_at = ""
            if position > 60000000:
                self.failures = 0
        if len([stamp for stamp in warnings if time.monotonic() - stamp < 30]) >= 10:
            self.fail("Se detectaron tiempos de vídeo discontinuos; reconectando la salida a YouTube.")
            self.heartbeat("retrying", self.last_error)
        elif time.monotonic() - self.progress_tick > 45:
            self.fail("La salida no ha avanzado durante 45 segundos; reconectando con YouTube.")
            self.heartbeat("retrying", self.last_error)
        else:
            self.heartbeat("sending" if self.last_progress_at else "connecting")

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception:
                    # No exception/command repr is logged: Popen errors can contain the key.
                    self.fail("No se pudo mantener la salida a YouTube. Revisa su configuración y el servicio local.")
                    self.heartbeat("retrying", self.last_error)
                self.stop.wait(1)
        finally:
            self.terminate()
            self.heartbeat("shutdown")
            self.owner.close()


def main():
    os.umask(0o077)
    relay = Relay()
    signal.signal(signal.SIGTERM, lambda *_: relay.stop.set())
    signal.signal(signal.SIGINT, lambda *_: relay.stop.set())
    relay.run()


if __name__ == "__main__":
    main()
