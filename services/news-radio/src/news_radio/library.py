"""Persistent article metadata and collection status in SQLite."""

from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import unicodedata
from urllib.parse import urlsplit

from news_radio.catalog import source_is_ready
from news_radio.connectors import matches_source

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


class NewsLibrary:
    def __init__(self, directory=None):
        directory = Path(directory or os.environ.get("NEWS_RADIO_DATA_DIR", "data"))
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "news.sqlite3"
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                    summary TEXT NOT NULL, published_at TEXT, updated_at TEXT,
                    discovered_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS article_sources (
                    article_id TEXT NOT NULL, source_id TEXT NOT NULL,
                    PRIMARY KEY (article_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS source_status (
                    source_id TEXT PRIMARY KEY, last_attempt_at TEXT NOT NULL,
                    last_success_at TEXT, article_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS platform_status (
                    platform TEXT PRIMARY KEY, last_request_at TEXT,
                    cooldown_until TEXT, rate_limit_failures INTEGER NOT NULL DEFAULT 0,
                    last_rate_limit_at TEXT
                );
            """)
            additions = {
                "articles": {"author": "TEXT NOT NULL DEFAULT ''", "linked_url": "TEXT NOT NULL DEFAULT ''",
                             "content_kind": "TEXT NOT NULL DEFAULT 'article'"},
                "source_status": {"next_retry_at": "TEXT"},
            }
            for table, columns in additions.items():
                existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                for column, definition in columns.items():
                    if column not in existing:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_source(self, source_id: str, articles: list[dict]):
        now = utc_now()
        with self._connect() as db:
            for article in articles:
                article_id = hashlib.sha256(article["url"].encode()).hexdigest()
                db.execute("""
                    INSERT INTO articles (id, url, title, summary, published_at, updated_at,
                        discovered_at, last_seen_at, author, linked_url, content_kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                        summary=excluded.summary,
                        published_at=COALESCE(excluded.published_at, articles.published_at),
                        updated_at=COALESCE(excluded.updated_at, articles.updated_at),
                        last_seen_at=excluded.last_seen_at,
                        author=CASE WHEN excluded.author != '' THEN excluded.author ELSE articles.author END,
                        linked_url=excluded.linked_url, content_kind=excluded.content_kind
                """, (article_id, article["url"], article["title"], article["summary"],
                      article["published_at"], article["updated_at"], now, now,
                      article.get("author", ""), article.get("linked_url", ""), article.get("content_kind", "article")))
                db.execute("INSERT OR IGNORE INTO article_sources VALUES (?, ?)", (article_id, source_id))
            db.execute("""
                INSERT INTO source_status(source_id, last_attempt_at, last_success_at, article_count, error)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(source_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at, article_count=excluded.article_count,
                    error=NULL, next_retry_at=NULL
            """, (source_id, now, now, len(articles)))

    def fail_source(self, source_id: str, error: str, next_retry_at=None, attempted_at=None):
        with self._connect() as db:
            db.execute("""
                INSERT INTO source_status(source_id, last_attempt_at, error, next_retry_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,
                    error=excluded.error, next_retry_at=excluded.next_retry_at
            """, (source_id, attempted_at or utc_now(), error[:500], next_retry_at))

    def statuses(self) -> dict:
        with self._connect() as db:
            return {row["source_id"]: dict(row) for row in db.execute("SELECT * FROM source_status")}

    def platform_status(self, platform: str) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM platform_status WHERE platform=?", (platform,)).fetchone()
            return dict(row) if row else {}

    def record_platform_request(self, platform: str, attempted_at: str):
        with self._connect() as db:
            db.execute("""
                INSERT INTO platform_status(platform, last_request_at) VALUES (?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    last_request_at=MAX(COALESCE(platform_status.last_request_at, ''), excluded.last_request_at)
            """, (platform, attempted_at))

    def pause_platform(self, platform: str, attempted_at: str, until: str):
        with self._connect() as db:
            db.execute("""
                INSERT INTO platform_status(platform, last_request_at, cooldown_until, rate_limit_failures, last_rate_limit_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    last_request_at=MAX(COALESCE(platform_status.last_request_at, ''), excluded.last_request_at),
                    cooldown_until=MAX(COALESCE(platform_status.cooldown_until, ''), excluded.cooldown_until),
                    rate_limit_failures=platform_status.rate_limit_failures+1,
                    last_rate_limit_at=excluded.last_rate_limit_at
                WHERE COALESCE(platform_status.last_rate_limit_at, '') < excluded.last_rate_limit_at
            """, (platform, attempted_at, until, attempted_at))

    def clear_platform_limit(self, platform: str):
        with self._connect() as db:
            db.execute("UPDATE platform_status SET cooldown_until=NULL, rate_limit_failures=0 WHERE platform=?", (platform,))

    def article(self, article_id: str) -> dict | None:
        """Read one saved item without contacting its source."""
        with self._connect() as db:
            row = db.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
            if row is None:
                return None
            article = dict(row)
            source_ids = [r[0] for r in db.execute("SELECT source_id FROM article_sources WHERE article_id=?", (article_id,))]
        article["source_ids"] = source_ids
        return article

    def news(self, sources: list[dict], *, query="", time_range="day", language="all", source_id="", platform="all", offset=0, limit=100) -> dict:
        def matches_platform(source):
            origin = source.get("platform", "web")
            return platform == "all" or origin == platform or (platform == "social" and origin != "web")

        active = {s["id"]: s for s in sources if s["enabled"] and source_is_ready(s) and matches_platform(s)
                  and (language == "all" or s.get("language") == language)
                  and (not source_id or s["id"] == source_id)}
        rows = []
        if active:
            slots = ",".join("?" for _ in active)
            with self._connect() as db:
                rows = db.execute(f"""
                    SELECT a.*, origin.source_id FROM articles a
                    JOIN article_sources origin ON origin.article_id=a.id
                    WHERE origin.source_id IN ({slots})
                    ORDER BY a.published_at DESC, a.discovered_at DESC
                """, list(active)).fetchall()
        days = {"day": 1, "week": 7, "month": 30, "year": 365}
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days[time_range]) if time_range else None
        terms = _fold(query).split()
        articles = {}
        undated = set()
        for row in rows:
            source = active[row["source_id"]]
            if not matches_source(dict(row), source):
                continue
            if terms and not all(term in _fold(row["title"] + " " + row["summary"]) for term in terms):
                continue
            if not row["published_at"]:
                undated.add(row["id"])
                if cutoff:
                    continue
            else:
                published = datetime.fromisoformat(row["published_at"])
                if published > now + timedelta(minutes=5) or (cutoff and published < cutoff):
                    continue
            if row["id"] in articles:
                articles[row["id"]]["sources"].append(source["name"])
                continue
            articles[row["id"]] = {
                "id": row["id"], "title": row["title"], "url": row["url"],
                "content": row["summary"], "published_at": row["published_at"] or "",
                "updated_at": row["updated_at"] or "", "discovered_at": row["discovered_at"],
                "source_name": (f"{urlsplit(row['url']).hostname} · SearXNG" if source.get("connector") == "searxng" else source["name"]), "source_id": source["id"],
                "sources": [source["name"]], "provider": "searxng" if source.get("connector") == "searxng" else "direct",
                "platform": source.get("platform", "web"), "content_kind": row["content_kind"],
                "author": row["author"], "linked_url": row["linked_url"],
            }
        results = list(articles.values())
        page = results[offset:offset + limit]
        return {"query": query, "count": len(page), "total_count": len(results), "offset": offset,
                "results": page, "undated_count": len(undated), "provider": "direct",
                "applied_time_range": time_range, "platform": platform, "searched_at": utc_now()}
