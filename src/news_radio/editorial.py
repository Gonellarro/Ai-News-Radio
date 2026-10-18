"""Manual editorial workflow, separate from collection and future publishing."""

import hashlib
import logging
import os
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit

from news_radio.article_text import MAX_TEXT, fetch_article
from news_radio.catalog import load_sources
from news_radio.editorial_store import EditorialStore
from news_radio.ollama import OllamaClient, OllamaError


class EditorialError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def text_source(article, material):
    """Identify the material's publisher, independently of its discovery feed."""
    host = (urlsplit(material["url"]).hostname or "").lower().removeprefix("www.")
    sources = load_sources()
    # A social extract belongs to the saved post, not to its external link.
    if material["url"] == article["url"]:
        for source in sources:
            if source["id"] in article.get("source_ids", []) and source.get("platform") in {"reddit", "mastodon", "bluesky"}:
                return source["name"]
    matches = []
    for source in sources:
        if source.get("platform", "web") != "web" or source.get("connector") == "searxng":
            continue
        domain = (urlsplit(source["url"]).hostname or "").lower().removeprefix("www.")
        if domain and (host == domain or host.endswith("." + domain)):
            matches.append((len(domain), source["name"]))
    if matches:
        return max(matches)[1]
    if not host:
        raise EditorialError("No se puede identificar la fuente del texto para la locución.")
    return host


def credit_script(script, source):
    """Append a deterministic spoken credit, without another model request."""
    credit = f"Fuente de esta noticia: {source.rstrip('. ')}."
    script = script.strip()
    if script.endswith(credit):
        return script
    if not script.endswith((".", "!", "?", "…")):
        script = script.rstrip(",;: ") + "."
    return f"{script}\n\n{credit}"


class EditorialService:
    def __init__(self, library):
        self.library = library
        self.store = EditorialStore(library.path)
        self.client = OllamaClient()
        self.lock = threading.Lock()
        self.prepare_lock = threading.Lock()
        self.active_id = None
        self.instructions_path = Path(os.environ.get("NEWS_RADIO_CONFIG_DIR", "config")) / "editorial.md"

    def instructions(self):
        try:
            text = self.instructions_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise EditorialError("No se puede leer config/editorial.md. Comprueba que existe y es accesible.", 503) from exc
        if not text or len(text) > 6000:
            raise EditorialError("config/editorial.md debe contener entre 1 y 6.000 caracteres.", 503)
        return text

    def info(self):
        return {"model": self.client.model, "url": self.client.url, "think": False,
                "instructions": self.instructions(), "instructions_file": "config/editorial.md",
                "active_id": self.active_id, "drafts": self.store.recent()}

    def article(self, article_id):
        article = self.library.article(article_id)
        if not article:
            raise EditorialError("La noticia no está en la biblioteca local.", 404)
        sources = {source["id"]: source for source in load_sources()}
        article["sources"] = [sources[s]["name"] for s in article["source_ids"] if s in sources]
        return article

    @staticmethod
    def excerpt(article):
        return {"text": article["summary"], "url": article["url"], "kind": "excerpt", "truncated": True,
                "note": "Solo se dispone del extracto del feed (hasta 1.200 caracteres). Puede estar cortado o incompleto; no es el artículo completo."}

    def workspace(self, article_id):
        article = self.article(article_id)
        return {"article": article, "material": self.store.material(article_id) or self.excerpt(article),
                "drafts": self.store.recent(article_id)}

    def prepare(self, article_id):
        article = self.article(article_id)
        with self.prepare_lock:
            existing = self.store.material(article_id)
            if existing:
                return existing
            social = article.get("content_kind") in {"social_post", "community_post"}
            target = article.get("linked_url") if social else article["url"]
            if not target:
                material = self.excerpt(article)
                material["note"] += " Esta publicación no tiene un enlace externo que descargar. No se consultan comentarios."
            else:
                try:
                    from news_radio.search_source import cached_material
                    material = cached_material(target) or fetch_article(target)
                except (OSError, ValueError, RecursionError) as exc:
                    if isinstance(exc, HTTPError):
                        reason = f"HTTP {exc.code}"
                        exc.close()
                    else:
                        reason = str(exc)[:250]
                    material = self.excerpt(article)
                    material["note"] += f" No se pudo extraer el enlace: {reason}. Puedes pegar el texto manualmente."
            # Also cache failed extraction so retries do not repeatedly hit the source.
            self.store.save_material(article_id, material)
            return material

    def generate(self, article_id, text=None, instructions=None, request_key=None):
        if request_key is not None:
            if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
                raise EditorialError("request_key debe tener entre 1 y 128 caracteres.")
            existing = self.store.by_request_key(request_key)
            if existing:
                return existing
        article = self.article(article_id)
        if instructions is None:
            instructions = self.instructions()
        elif not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 6000:
            raise EditorialError("Las instrucciones deben tener entre 1 y 6.000 caracteres.")
        material = self.store.material(article_id) or self.excerpt(article)
        if text is not None:
            if not isinstance(text, str):
                raise EditorialError("El texto debe ser una cadena de caracteres.")
            if text.strip() != material["text"].strip():
                material = {"text": text.strip(), "url": material["url"], "kind": "manual", "truncated": False,
                            "note": "Texto aportado o editado manualmente por el usuario. No se ha verificado ni contrastado automáticamente."}
        if not 80 <= len(material["text"]) <= MAX_TEXT:
            raise EditorialError(f"El texto de origen debe tener entre 80 y {MAX_TEXT:,} caracteres.")
        source = text_source(article, material)
        if not self.lock.acquire(blocking=False):
            raise EditorialError("Ollama ya está redactando otra noticia. Espera a que termine.", 409)
        try:
            snapshot = {"article": article, "material": material, "instructions": instructions,
                        "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                        "model": self.client.model, "think": False, "spoken_source": source}
            draft = self.store.create(article_id, snapshot, request_key=request_key)
            self.active_id = draft["id"]
            threading.Thread(target=self._write, args=(draft,), name="editorial-writer", daemon=True).start()
            return draft
        except Exception:
            self.active_id = None
            self.lock.release()
            raise

    def _write(self, draft):
        try:
            snapshot = draft["snapshot"]
            result = self.client.write(snapshot["instructions"], snapshot["article"], snapshot["material"])
            result["script"] = credit_script(result["script"], snapshot["spoken_source"])
            result["word_count"] = len(result["script"].split())
            self.store.finish(draft["id"], result=result)
        except OllamaError as exc:
            self.store.finish(draft["id"], error=str(exc))
        except Exception:
            logging.exception("Editorial generation failed")
            self.store.finish(draft["id"], error="No se pudo completar el borrador. Revisa los registros del servicio.")
        finally:
            self.active_id = None
            self.lock.release()

    def draft(self, draft_id):
        draft = self.store.get(draft_id)
        if not draft:
            raise EditorialError("No se encuentra ese borrador.", 404)
        return draft

    def review(self, draft_id, title, script):
        draft = self.draft(draft_id)
        if draft["status"] not in {"ready", "reviewed"}:
            raise EditorialError("Solo se puede revisar un borrador terminado.", 409)
        if not isinstance(title, str) or not isinstance(script, str) or not title.strip() or not script.strip() or len(title) > 500 or len(script) > 12000:
            raise EditorialError("Escribe un titular (hasta 500 caracteres) y un guion (hasta 12.000).")
        return self.store.review(draft_id, title.strip(), script.strip())
