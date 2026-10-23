from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import threading
from urllib.parse import urlsplit, parse_qs

from news_orchestrator import config, piper_assets, visuals, youtube_control
from news_orchestrator.pipeline import Pipeline
from news_orchestrator.client import RemoteError
from news_orchestrator.dashboard import Dashboard
from news_orchestrator.playlist_control import Conflict


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/health":
                workers = {thread.name: thread.is_alive() for thread in self.server.pipeline.threads}
                healthy = bool(workers) and all(workers.values())
                self.json(200 if healthy else 503,
                          {"status": "ok" if healthy else "degraded", "service": "news-orchestrator",
                           "output": "local", "workers": workers})
            elif path == "/api/status":
                self.json(200, self.server.pipeline.status())
            elif path.startswith("/api/dashboard/"):
                self.json(200, self.server.dashboard.get(path.removeprefix("/api/dashboard/"), parse_qs(urlsplit(self.path).query)))
            elif path == "/api/youtube":
                self.json(200, youtube_control.public_status())
            elif path == "/api/youtube/logs":
                self.json(200, {"logs": youtube_control.logs()})
            elif path == "/api/branding":
                self.json(200, visuals.public_catalog())
            elif path == "/api/narration":
                settings = config.load()
                self.json(200, {"tts_engine": settings["tts_engine"], "piper_voice": settings["piper_voice"],
                                "voice_mode": settings["voice_mode"], "qwen_voice_id": settings["qwen_voice_id"],
                                "voice_name": settings["voice_name"],
                                "qwen_web_url": os.environ.get("QWENTTS_PUBLIC_URL", self.server.pipeline.tts.url),
                                "piper_voices": piper_assets.public_catalogue()})
            elif path == "/api/voices":
                settings = config.load()
                try:
                    data = {**self.server.pipeline.tts.request("/api/voices", timeout=5), "available": True}
                except (OSError, RemoteError):
                    data = {"voices": [], "available": False,
                            "notice": "Qwen no está disponible. Activa su perfil de Docker para gestionar voces clonadas. Piper funciona sin ese servicio."}
                self.json(200, {**data, "voice_names": settings["voice_names"], "voice_exclude": settings["voice_exclude"]})
            elif path == "/samples/piper-davefx.mp3":
                self.file(config.DATA / "previews" / "piper-davefx.mp3", "audio/mpeg")
            elif match := re.fullmatch(r"/branding/logos/([a-z0-9-]+\.png)", path):
                if (visuals.LOGOS / match[1]).is_symlink():
                    raise ValueError("Logo no válido.")
                self.file(visuals.LOGOS / match[1], "image/png")
            elif (path in {"/", "/index.html", "/app.js", "/styles.css", "/dashboard.css", "/youtube-guide.html", "/branding.html", "/branding.js", "/vendor/hls.light.min.js"}
                  or re.fullmatch(r"/modules/[a-z-]+\.js", path)):
                name = "index.html" if path == "/" else path[1:]
                media = "text/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "text/html"
                self.file(config.WEB / name, media + "; charset=utf-8")
            elif path == "/live/index.m3u8":
                self.file(config.DATA / "hls" / "index.m3u8", "application/vnd.apple.mpegurl")
            elif match := re.fullmatch(r"/live/(segment-\d+\.ts)", path):
                self.file(config.DATA / "hls" / match[1], "video/mp2t")
            elif match := re.fullmatch(r"/media/([a-f0-9]{64})/(video\.mp4|audio\.mp3|poster\.png)", path):
                media = "video/mp4" if match[2].endswith("mp4") else "image/png" if match[2].endswith("png") else "audio/mpeg"
                self.file(config.DATA / "media" / match[1] / match[2], media)
            else:
                self.json(404, {"error": "Ruta no encontrada."})
        except sqlite3.OperationalError:
            logging.exception("Dashboard database operation failed")
            self.json(503, {"error": "La base de datos está ocupada temporalmente. Vuelve a intentarlo en unos segundos."})
        except (ValueError, OSError, RemoteError) as exc:
            self.json(503, {"error": str(exc)})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self.json(403, {"error": "Origen no permitido."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.json(415, {"error": "Se requiere JSON."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            path = urlsplit(self.path).path
            maximum = 17 * 1024 * 1024 if path.startswith("/api/dashboard/voices/") else 256 * 1024
            if self.headers.get("Transfer-Encoding") or not 1 <= length <= maximum:
                raise ValueError("Cuerpo de petición no válido.")
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("Se requiere un objeto JSON.")
            path = urlsplit(self.path).path
            if path.startswith("/api/dashboard/"):
                self.json(200, self.server.dashboard.post(path.removeprefix("/api/dashboard/"), value))
            elif path == "/api/scan":
                if not self.server.pipeline.scanning:
                    self.server.pipeline.manual_requested.set()
                self.json(202, {"status": "in_progress" if self.server.pipeline.scanning else "scheduled"})
            elif path == "/api/narration":
                if value.get("tts_engine") == "qwen" and value.get("voice_mode") == "fixed":
                    voices = self.server.pipeline.tts.request("/api/voices", timeout=5)["voices"]
                    if not any(v["id"] == value.get("qwen_voice_id") and v.get("enabled", True) for v in voices):
                        raise ValueError("Selecciona una voz activa de Qwen. Actualiza la biblioteca si acabas de modificarla.")
                settings = config.save_narration(value)
                self.server.pipeline.store.event(f"Motor de locución configurado: {settings['tts_engine']}.")
                self.json(200, settings)
            elif path == "/api/youtube/key":
                self.json(200, youtube_control.update_key(value.get("key")))
            elif path == "/api/youtube/start":
                self.json(202, youtube_control.start())
            elif path == "/api/youtube/stop":
                self.json(202, youtube_control.stop())
            elif path == "/api/youtube/reconnect":
                self.json(202, youtube_control.reconnect())
            else:
                self.json(404, {"error": "Ruta no encontrada."})
        except Conflict as exc:
            self.json(409, {"error": str(exc)})
        except (ValueError, UnicodeError) as exc:
            self.json(400, {"error": str(exc)})
        except sqlite3.OperationalError:
            logging.exception("Dashboard database write failed")
            self.json(503, {"error": "La base de datos está ocupada temporalmente. Recarga los valores antes de volver a guardar."})
        except OSError:
            self.json(503, {"error": "No se pudo guardar la configuración. Comprueba los permisos de la carpeta correspondiente."})
        except RemoteError as exc:
            self.json(503, {"error": str(exc)})

    def json(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def file(self, path, media):
        if not path.is_file():
            self.json(404, {"error": "El recurso todavía no está disponible."})
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = False
        requested = self.headers.get("Range")
        if requested and (media.startswith("video/") or media.startswith("audio/")):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            if match[1]:
                start = int(match[1])
                if match[2]:
                    end = min(end, int(match[2]))
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        if "/live/" not in (args[0] if args else "") and "/api/status" not in (args[0] if args else ""):
            logging.info("%s - %s", self.address_string(), fmt % args)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pipeline = Pipeline()
    server = ThreadingHTTPServer(("0.0.0.0", 8792), Handler)
    server.pipeline = pipeline
    server.dashboard = Dashboard(pipeline)
    def shutdown(*_):
        pipeline.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    pipeline.start()
    logging.info("Orquestador automático listo en el puerto 8792; salida local.")
    try:
        server.serve_forever()
    finally:
        pipeline.close()
        server.server_close()


if __name__ == "__main__":
    main()
