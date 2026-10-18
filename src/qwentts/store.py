from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "tts.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, request TEXT NOT NULL, result TEXT,
                    error TEXT NOT NULL DEFAULT ''
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "request_key" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN request_key TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS tts_request_key ON jobs(request_key) WHERE request_key IS NOT NULL")
            db.execute("UPDATE jobs SET status='error', error=?, updated_at=? WHERE status IN ('preparing', 'waiting', 'running')",
                       ("La generación se interrumpió al reiniciar el servicio.", now()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        item = dict(row)
        item["request"] = json.loads(item["request"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def create(self, request, request_key=None):
        job_id = uuid.uuid4().hex
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('preparing','queued','waiting','running')").fetchone()[0] >= 10:
                raise ValueError("La cola ya tiene diez trabajos pendientes. Espera a que termine alguno.")
            db.execute("INSERT INTO jobs(id,status,created_at,updated_at,request,result,error,request_key) VALUES (?, 'preparing', ?, ?, ?, NULL, '', ?)",
                       (job_id, now(), now(), json.dumps(request, ensure_ascii=False), request_key))
        return self.get(job_id)

    def by_request_key(self, key):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE request_key=?", (key,)).fetchone())

    def by_request_prefix(self, prefix):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute(
                "SELECT * FROM jobs WHERE substr(request_key,1,?)=? ORDER BY created_at", (len(prefix), prefix))]

    def get(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 30")]

    def next(self):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone())

    def update(self, job_id, status, result=None, error=""):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?, updated_at=?, result=?, error=? WHERE id=?",
                       (status, now(), json.dumps(result, ensure_ascii=False) if result else None, error, job_id))
