"""HTTP interface for the News Radio search prototype."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import os
import re

from news_radio.search import SearchError, search_news
from news_radio.catalog import load_sources
from news_radio.collector import NewsCollector
from news_radio.library import NewsLibrary
from news_radio.editorial import EditorialError, EditorialService
from news_radio.ollama import OllamaError


WEB_DIR = Path(os.environ.get("WEB_DIR", Path(__file__).resolve().parents[2] / "web"))


class NewsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "service": "news-radio"})
        elif parsed.path == "/api/search":
            self._search(parse_qs(parsed.query, keep_blank_values=True))
        elif parsed.path == "/api/news":
            self._news(parse_qs(parsed.query, keep_blank_values=True))
        elif parsed.path == "/api/sources":
            try:
                self._json(200, self.server.collector.status())
            except (ValueError, OSError) as exc:
                self._json(503, {"error": f"No se pudo leer el catálogo de fuentes: {exc}"})
        elif parsed.path.startswith("/api/editorial"):
            self._editorial_get(parsed.path, parse_qs(parsed.query))
        elif parsed.path in {"/", "/index.html"}:
            self._file("index.html", "text/html; charset=utf-8")
        elif parsed.path == "/app.js":
            self._file("app.js", "text/javascript; charset=utf-8")
        elif parsed.path == "/editorial.js":
            self._file("editorial.js", "text/javascript; charset=utf-8")
        elif parsed.path == "/styles.css":
            self._file("styles.css", "text/css; charset=utf-8")
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "Origen no permitido."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._json(415, {"error": "Se requiere Content-Type: application/json."})
            return
        path = urlparse(self.path).path
        if path == "/api/refresh":
            if not self.server.collector.refreshing:
                self.server.collector.request_refresh()
            self._json(202, {"status": "refreshing"})
        elif path.startswith("/api/editorial/"):
            self._editorial_post(path)
        else:
            self.send_error(404)

    def _editorial_get(self, path, params):
        service = self.server.editorial
        try:
            if path == "/api/editorial":
                payload = service.info()
            elif path == "/api/editorial/connection":
                payload = service.client.status()
            elif path == "/api/editorial/article":
                payload = service.workspace((params.get("id") or [""])[0])
            elif re.fullmatch(r"/api/editorial/drafts/[a-f0-9]{32}", path):
                payload = service.draft(path.rsplit("/", 1)[-1])
            else:
                self._json(404, {"error": "Ruta editorial no encontrada."})
                return
            self._json(200, payload)
        except EditorialError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (OllamaError, OSError, ValueError) as exc:
            self._json(503, {"error": str(exc)})

    def _editorial_post(self, path):
        service = self.server.editorial
        try:
            if self.headers.get("Transfer-Encoding"):
                raise EditorialError("Se requiere un cuerpo JSON con Content-Length.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise EditorialError("Longitud de petición no válida.") from exc
            if length < 1 or length > 128 * 1024:
                raise EditorialError("El cuerpo de la petición debe tener entre 1 byte y 128 KiB.", 413)
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError) as exc:
                raise EditorialError("El cuerpo de la petición no es JSON válido.") from exc
            if not isinstance(data, dict):
                raise EditorialError("La petición debe contener un objeto JSON.")
            if path in {"/api/editorial/prepare", "/api/editorial/generate"}:
                article_id = data.get("article_id")
                if not isinstance(article_id, str) or not re.fullmatch(r"[a-f0-9]{64}", article_id):
                    raise EditorialError("Selecciona una noticia de la biblioteca local.")
                if path.endswith("/prepare"):
                    self._json(200, {"material": service.prepare(article_id)})
                else:
                    self._json(202, service.generate(article_id, data.get("text"), data.get("instructions"), data.get("request_key")))
            elif re.fullmatch(r"/api/editorial/drafts/[a-f0-9]{32}/review", path):
                self._json(200, service.review(path.split("/")[-2], data.get("title"), data.get("script")))
            else:
                self._json(404, {"error": "Ruta editorial no encontrada."})
        except EditorialError as exc:
            self._json(exc.status, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self._json(503, {"error": str(exc)})

    def _news(self, params: dict[str, list[str]]) -> None:
        query = (params.get("q") or [""])[0].strip()
        time_range = (params.get("time_range") or ["day"])[0]
        language = (params.get("language") or ["all"])[0]
        source_id = (params.get("source_id") or [""])[0]
        platform = (params.get("platform") or ["web"])[0]
        if time_range not in {"", "day", "week", "month", "year"} or language not in {"all", "en", "es"}:
            self._json(400, {"error": "El periodo o el idioma no es válido."})
            return
        if platform not in {"web", "all", "social", "reddit", "mastodon", "bluesky"}:
            self._json(400, {"error": "La plataforma seleccionada no es válida."})
            return
        if len(query) > 300:
            self._json(400, {"error": "La búsqueda no puede superar los 300 caracteres."})
            return
        try:
            offset = int((params.get("offset") or ["0"])[0])
            limit = int((params.get("limit") or ["100"])[0])
            if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
                raise ValueError()
        except ValueError:
            self._json(400, {"error": "Paginación no válida: offset >= 0 y limit entre 1 y 100."})
            return
        try:
            sources = load_sources()
            if source_id and source_id not in {s["id"] for s in sources}:
                self._json(400, {"error": "La fuente seleccionada no existe en el catálogo."})
                return
            payload = self.server.library.news(sources, query=query, time_range=time_range,
                                               language=language, source_id=source_id, platform=platform,
                                               offset=offset, limit=limit)
            payload["refreshing"] = self.server.collector.refreshing
        except (ValueError, OSError) as exc:
            self._json(503, {"error": f"No se pudo leer el catálogo de fuentes: {exc}"})
            return
        self._json(200, payload)

    def _search(self, params: dict[str, list[str]]) -> None:
        query = (params.get("q") or [""])[0].strip()
        time_range = (params.get("time_range") or [""])[0]
        language = (params.get("language") or ["all"])[0]
        category = (params.get("category") or ["news"])[0]
        if not query:
            self._json(400, {"error": "Escribe un tema o unas palabras para buscar."})
            return
        if len(query) > 300:
            self._json(400, {"error": "La búsqueda no puede superar los 300 caracteres."})
            return
        try:
            payload = search_news(query, time_range=time_range, language=language, category=category)
        except SearchError as exc:
            self._json(exc.status, {"error": str(exc)})
            return
        self._json(200, payload)

    def _file(self, filename: str, content_type: str) -> None:
        try:
            content = (WEB_DIR / filename).read_bytes()
        except OSError:
            self.send_error(500, "No se pudo cargar la interfaz web.")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status: int, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8790"))
    server = ThreadingHTTPServer(("0.0.0.0", port), NewsHandler)
    server.library = NewsLibrary()
    server.editorial = EditorialService(server.library)
    server.collector = NewsCollector(server.library)
    server.collector.start()
    print(f"News Radio listening on port {port}; direct sources every {server.collector.interval}s")
    try:
        server.serve_forever()
    finally:
        server.collector.stop()
        server.server_close()


if __name__ == "__main__":
    main()
