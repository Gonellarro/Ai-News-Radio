"""Optional dated SearXNG discovery, with bounded and cached page extraction."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import urlsplit

from news_radio.article_text import fetch_article
from news_radio.feeds import normalize_url, parse_date, plain_text
from news_radio.search import SearchError, search_news


@contextmanager
def cache():
    directory = Path(os.environ.get("NEWS_RADIO_DATA_DIR", "data"))
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "search-pages.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, payload TEXT, error TEXT, fetched_at TEXT NOT NULL)")
        yield db
    finally:
        db.close()


def cached_material(url):
    with cache() as db:
        row = db.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()
    if row and row["payload"] and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=1):
        return json.loads(row["payload"])
    return None


def resolve_material(url):
    with cache() as db:
        row = db.execute("SELECT * FROM pages WHERE url=?", (url,)).fetchone()
    if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=1):
        return json.loads(row["payload"]) if row["payload"] else None
    material, error = None, ""
    try:
        material = fetch_article(url)
    except (OSError, ValueError, RecursionError) as exc:
        error = str(exc)[:500]
        if isinstance(exc, HTTPError):
            exc.close()
    with cache() as db:
        with db:
            db.execute("INSERT INTO pages VALUES (?,?,?,?) ON CONFLICT(url) DO UPDATE SET payload=excluded.payload,error=excluded.error,fetched_at=excluded.fetched_at",
                       (url, json.dumps(material, ensure_ascii=False) if material else None,
                        error, datetime.now(timezone.utc).isoformat()))
    return material


def fetch_search_source(source):
    articles, seen, errors = [], set(), []
    raw_count, undated = 0, 0
    # At most four undated pages per source and cycle; failed extractions are
    # cached too. Reddit threads remain forbidden by the shared article reader.
    remaining = 4
    now = datetime.now(timezone.utc)
    age = {"day": 1, "week": 7, "month": 30}[source.get("time_range", "week")]
    for query in source["queries"]:
        try:
            result = search_news(query, time_range=source.get("time_range", "week"),
                                 language=source.get("language", "all"), category=source.get("category", "news"))
        except SearchError as exc:
            errors.append(str(exc))
            continue
        errors.extend(result.get("warnings", []))
        for item in result["results"][:20]:
            raw_count += 1
            url = normalize_url(item["url"])
            if not url or url in seen:
                continue
            seen.add(url)
            date = parse_date(item.get("published_at", ""))
            summary = plain_text(item.get("content", ""))
            if not date:
                material = cached_material(url)
                if material is None and remaining:
                    remaining -= 1
                    material = resolve_material(url)
                if material:
                    date = material.get("published_at")
                    summary = material["text"][:1200]
            if not date:
                undated += 1
                continue
            published = datetime.fromisoformat(date)
            if not now - timedelta(days=age) <= published <= now + timedelta(minutes=5):
                continue
            articles.append({"title": plain_text(item["title"]), "url": url, "summary": summary[:1200],
                             "published_at": date, "updated_at": None, "author": "", "linked_url": ""})
    if not articles and errors:
        raise ValueError("SearXNG no aportó noticias fechadas utilizables: " + "; ".join(dict.fromkeys(errors))[:400])
    if not articles and undated:
        raise ValueError(f"SearXNG devolvió {raw_count} resultados; sin noticias con fecha de publicación utilizable. No se usa la fecha de descarga.")
    if errors:
        logging.warning("%s: errores parciales de SearXNG: %s", source["id"], "; ".join(dict.fromkeys(errors))[:500])
    return articles
