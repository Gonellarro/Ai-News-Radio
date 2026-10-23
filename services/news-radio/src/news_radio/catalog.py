"""Editable source catalog. Configuration is reloaded on every collection."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def source_is_ready(source: dict) -> bool:
    connector = source.get("connector", "rss")
    if connector == "bluesky_author":
        return bool(source.get("actor"))
    if connector == "bluesky_feed":
        return bool(source.get("feed"))
    if connector == "searxng":
        return bool(source.get("queries"))
    if connector == "newsroom":
        return bool(source.get("url") and source.get("article_path"))
    return bool(source.get("feed_url"))


def load_sources(data=None) -> list[dict]:
    root = Path(os.environ.get("NEWS_RADIO_CONFIG_DIR", Path(__file__).resolve().parents[2] / "config"))
    if data is None:
        data = json.loads((root / "sources.json").read_text(encoding="utf-8"))
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list):
        raise ValueError("sources.json debe contener una lista sources.")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Cada fuente debe ser un objeto.")
        for key in ("id", "name", "url"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError(f"Falta el campo {key} en una fuente.")
        if source["id"] in seen:
            raise ValueError(f"Identificador duplicado: {source['id']}")
        seen.add(source["id"])
        if not isinstance(source.get("enabled"), bool):
            raise ValueError(f"enabled debe ser true o false: {source['id']}")
        connector = source.get("connector", "rss")
        if not isinstance(connector, str) or connector not in {"rss", "bluesky_author", "bluesky_feed", "searxng", "newsroom"}:
            raise ValueError(f"Conector no admitido: {source['id']}")
        if not isinstance(source.get("platform", "web"), str) or source.get("platform", "web") not in {"web", "reddit", "mastodon", "bluesky"}:
            raise ValueError(f"Plataforma no admitida: {source['id']}")
        if connector == "bluesky_author" and not isinstance(source.get("actor"), str):
            raise ValueError(f"Falta actor de Bluesky: {source['id']}")
        if connector == "newsroom" and (
            not isinstance(source.get("article_path"), str)
            or not source["article_path"].startswith("/")
            or source["article_path"].startswith("//")
            or "?" in source["article_path"] or "#" in source["article_path"]
        ):
            raise ValueError(f"article_path debe ser una ruta local de noticias: {source['id']}")
        if connector == "searxng":
            queries = source.get("queries")
            if (not isinstance(queries, list) or not 1 <= len(queries) <= 4
                    or any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 300 for q in queries)):
                raise ValueError(f"queries debe contener entre una y cuatro búsquedas: {source['id']}")
            if not isinstance(source.get("category", "news"), str) or source.get("category", "news") not in {"news", "general"}:
                raise ValueError(f"Categoría de SearXNG no válida: {source['id']}")
            if not isinstance(source.get("time_range", "week"), str) or source.get("time_range", "week") not in {"day", "week", "month"}:
                raise ValueError(f"Periodo de SearXNG no válido: {source['id']}")
        if connector == "bluesky_feed" and (
            not isinstance(source.get("feed"), str)
            or not source["feed"].startswith("at://did:")
            or "/app.bsky.feed.generator/" not in source["feed"]
        ):
            raise ValueError(f"Identificador de feed Bluesky inválido: {source['id']}")
        keywords = source.get("keywords", [])
        if not isinstance(source.get("require_link", False), bool):
            raise ValueError(f"require_link debe ser true o false: {source['id']}")
        if "refresh_seconds" in source and (type(source["refresh_seconds"]) is not int or source["refresh_seconds"] < 60):
            raise ValueError(f"refresh_seconds debe ser un entero de al menos 60 segundos: {source['id']}")
        if not isinstance(keywords, list) or any(not isinstance(k, str) or not k.strip() for k in keywords):
            raise ValueError(f"keywords debe ser una lista de palabras o frases: {source['id']}")
        for key in ("url", "feed_url"):
            url = source.get(key)
            if key == "feed_url" and url is None:
                continue
            if not isinstance(url, str):
                raise ValueError(f"{key} debe ser una URL o null: {source['id']}")
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(f"URL inválida en {key}: {source['id']}")
    return sources
