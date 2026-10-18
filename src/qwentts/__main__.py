"""Lightweight HTTP control plane; heavy dependencies live only in worker.py."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
from urllib.parse import urlsplit

from qwentts.config import WEB
from qwentts.service import Service


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        service = self.server.service
        try:
            if path == "/health":
                self.json(200, {"status": "ok", "service": "qwentts"})
            elif path == "/api/status":
                self.json(200, service.status())
            elif path == "/api/voices":
                self.json(200, {"voices": service.voices.list()})
            elif path == "/api/jobs":
                self.json(200, {"jobs": [service.job(job["id"]) for job in service.store.list()]})
            elif match := re.fullmatch(r"/api/jobs/([a-f0-9]{32})", path):
                self.json(200, service.job(match[1]))
            elif match := re.fullmatch(r"/api/jobs/([a-f0-9]{32})/audio\.(mp3|wav)", path):
                job = service.job(match[1])
                if job["status"] == "purged":
                    self.json(410, {"error": "Los archivos de esta locución se eliminaron al retirar su noticia de la parrilla."})
                elif job["status"] != "ready":
                    self.json(409, {"error": "El audio todavía no está terminado."})
                else:
                    extension = match[2]
                    self.file(service.directory(match[1]) / f"output.{extension}", "audio/mpeg" if extension == "mp3" else "audio/wav")
            elif match := re.fullmatch(r"/api/voices/([a-f0-9]{32})/audio", path):
                self.file(Path(service.voices.get(match[1])["reference"]), "audio/wav")
            elif path in {"/", "/index.html", "/app.js", "/styles.css"}:
                filename = "index.html" if path == "/" else path[1:]
                media = {"index.html": "text/html", "app.js": "text/javascript", "styles.css": "text/css"}[filename]
                self.file(WEB / filename, media + "; charset=utf-8")
            else:
                self.json(404, {"error": "Ruta no encontrada."})
        except ValueError as exc:
            self.json(400, {"error": str(exc)})
        except (OSError, subprocess.SubprocessError) as exc:
            logging.exception("GET failed")
            self.json(503, {"error": f"No se pudo leer el recurso: {exc}"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self.json(403, {"error": "Origen no permitido."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self.json(415, {"error": "Se requiere Content-Type: application/json."})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Se requiere Content-Length.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 17 * 1024 * 1024:
                self.json(413, {"error": "La petición supera el límite de carga."})
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON.")
            path = urlsplit(self.path).path
            service = self.server.service
            if path == "/api/voices":
                self.json(201, service.voices.upload(data))
            elif path == "/api/voices/import":
                self.json(200, service.voices.import_folder())
            elif path == "/api/jobs":
                self.json(202, service.enqueue(data))
            elif path == "/api/jobs/purge-news":
                self.json(200, service.purge_news(data.get("story_id")))
            elif match := re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", path):
                self.json(200, service.cancel(match[1]))
            else:
                self.json(404, {"error": "Ruta no encontrada."})
        except (ValueError, UnicodeError) as exc:
            self.json(400, {"error": str(exc)})
        except (OSError, subprocess.SubprocessError) as exc:
            logging.exception("POST failed")
            self.json(503, {"error": f"No se pudo completar la operación: {exc}"})

    def json(self, status, data):
        content = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def file(self, path, media):
        if not path.is_file():
            self.json(404, {"error": "Archivo no encontrado."})
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        partial = False
        if requested and media.startswith("audio/"):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                self.send_error(416)
                return
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), end) if match[2] else end
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
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = source.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def log_message(self, format, *args):
        logging.info("%s - %s", self.address_string(), format % args)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = Service()
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8791"))), Handler)
    server.service = service
    service.start()

    def shutdown(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logging.info("Qwen TTS API lista en el puerto %s. Modelo bajo demanda.", server.server_port)
    try:
        server.serve_forever()
    finally:
        service.stop()
        server.server_close()


if __name__ == "__main__":
    main()
