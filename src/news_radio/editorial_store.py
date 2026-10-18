"""Editorial snapshots and drafts in the existing persistent database."""

from contextlib import contextmanager
import json
import sqlite3
import uuid

from news_radio.library import utc_now


class EditorialStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS article_materials (
                    article_id TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS editorial_drafts (
                    id TEXT PRIMARY KEY, article_id TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL, result TEXT, error TEXT NOT NULL DEFAULT '',
                    edited_title TEXT, edited_script TEXT
                );
                CREATE INDEX IF NOT EXISTS drafts_by_article ON editorial_drafts(article_id, created_at DESC);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(editorial_drafts)")}
            if "request_key" not in columns:
                db.execute("ALTER TABLE editorial_drafts ADD COLUMN request_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS editorial_request_key ON editorial_drafts(request_key) WHERE request_key IS NOT NULL")
            db.execute("UPDATE editorial_drafts SET status='error', error=?, updated_at=? WHERE status='generating'",
                       ("La generación se interrumpió al reiniciar el servicio. Puedes volver a generarla.", utc_now()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def material(self, article_id):
        with self.connect() as db:
            row = db.execute("SELECT payload, fetched_at FROM article_materials WHERE article_id=?", (article_id,)).fetchone()
            return {**json.loads(row["payload"]), "fetched_at": row["fetched_at"]} if row else None

    def save_material(self, article_id, material):
        with self.connect() as db:
            db.execute("INSERT INTO article_materials VALUES (?, ?, ?) ON CONFLICT(article_id) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
                       (article_id, json.dumps(material, ensure_ascii=False), utc_now()))

    def create(self, article_id, snapshot, request_key=None):
        draft_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as db:
            db.execute("INSERT INTO editorial_drafts(id, article_id, status, created_at, updated_at, snapshot, request_key) VALUES (?, ?, 'generating', ?, ?, ?, ?)",
                       (draft_id, article_id, now, now, json.dumps(snapshot, ensure_ascii=False), request_key))
        return self.get(draft_id)

    def by_request_key(self, key):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM editorial_drafts WHERE request_key=?", (key,)).fetchone())

    def finish(self, draft_id, result=None, error=""):
        with self.connect() as db:
            db.execute("UPDATE editorial_drafts SET status=?, result=?, error=?, updated_at=? WHERE id=?",
                       ("error" if error else "ready", json.dumps(result, ensure_ascii=False) if result else None, error, utc_now(), draft_id))

    @staticmethod
    def decode(row):
        if row is None:
            return None
        value = dict(row)
        value["snapshot"] = json.loads(value["snapshot"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def get(self, draft_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM editorial_drafts WHERE id=?", (draft_id,)).fetchone())

    def recent(self, article_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT id, article_id, status, created_at, snapshot, result, edited_title FROM editorial_drafts "
                              + ("WHERE article_id=? " if article_id else "") + "ORDER BY created_at DESC LIMIT 20",
                              (article_id,) if article_id else ()).fetchall()
        drafts = []
        for row in rows:
            title = row["edited_title"]
            if title is None:
                title = json.loads(row["result"])["title"] if row["result"] else json.loads(row["snapshot"])["article"]["title"]
            drafts.append({"id": row["id"], "article_id": row["article_id"], "status": row["status"],
                           "created_at": row["created_at"], "title": title})
        return drafts

    def review(self, draft_id, title, script):
        with self.connect() as db:
            db.execute("UPDATE editorial_drafts SET status='reviewed', edited_title=?, edited_script=?, updated_at=? WHERE id=? AND status IN ('ready', 'reviewed')",
                       (title, script, utc_now(), draft_id))
        return self.get(draft_id)
