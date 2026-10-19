from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from news_orchestrator import balancing, narration, rotation

MAX_RETRIES = 3  # One initial attempt, followed by at most three retries.


def now():
    return datetime.now(timezone.utc).isoformat()


def after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def event_key(article):
    social = article.get("content_kind") in {"social_post", "community_post"}
    url = article.get("linked_url") if social else article["url"]
    parsed = urlsplit(url or article["url"])
    query = [(key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith("utm_")
             and key.lower() not in {"fbclid", "gclid"}]
    canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(sorted(query)), ""))
    return hashlib.sha256(canonical.encode()).hexdigest()


def title_key(title):
    title = unicodedata.normalize("NFKD", title.casefold())
    terms = re.findall(r"[^\W_]+", "".join(c for c in title if not unicodedata.combining(c)))
    return hashlib.sha256(" ".join(terms).encode()).hexdigest() if len(terms) >= 6 else None


def content_key(article):
    text = re.sub(r"https?://\S+", "", article.get("content", ""))
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text.casefold()))
    normalized = " ".join(words)
    return hashlib.sha256(normalized.encode()).hexdigest() if len(words) >= 12 and len(normalized) >= 80 else None


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "orchestrator.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, article_id TEXT NOT NULL, published_at TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    article TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    stage TEXT NOT NULL DEFAULT 'queued', active INTEGER NOT NULL DEFAULT 0,
                    work TEXT NOT NULL DEFAULT '{}', result TEXT, failures INTEGER NOT NULL DEFAULT 0,
                    retry_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', title_key TEXT
                );
                CREATE INDEX IF NOT EXISTS by_publication ON jobs(published_at DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS unique_title ON jobs(title_key) WHERE title_key IS NOT NULL;
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    job_id TEXT, message TEXT NOT NULL
                );
            """)
            db.execute("BEGIN IMMEDIATE")  # Serialize schema upgrades across processes.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "content_key" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN content_key TEXT")
            for name in ("artifacts_deleted_at", "tts_deleted_at"):
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
            if "queue_rank" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN queue_rank INTEGER")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_content ON jobs(content_key) WHERE content_key IS NOT NULL")
            db.execute("""CREATE TABLE IF NOT EXISTS source_publications (
                job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_name TEXT NOT NULL,
                platform TEXT NOT NULL, recorded_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS publications_by_source ON source_publications(source_id)")
            db.execute("CREATE INDEX IF NOT EXISTS publications_by_time ON source_publications(recorded_at)")
            # Backfill once, including retired clips whose media was removed.
            # Each clip counts once, never once per loop, retry or visual update.
            if not db.execute("SELECT 1 FROM state WHERE key='source_history_initialized_at'").fetchone():
                for row in db.execute("SELECT * FROM jobs WHERE status='ready'").fetchall():
                    self._record_publication(db, self.decode(row), row["updated_at"])
                db.execute("INSERT INTO state VALUES ('source_history_initialized_at',?)", (json.dumps(now()),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            # Resume in-flight remote work using its saved IDs. Completed or
            # exhausted jobs are never revived by a restart.
            db.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (now(),))
            self._discard_exhausted(db)

    @staticmethod
    def _discard_exhausted(db):
        # Apply the limit to retries persisted by older versions, too. An
        # interrupted running job, recovered as queued, may finish its attempt.
        exhausted = db.execute("SELECT id,error FROM jobs WHERE status='retry' AND failures>?",
                               (MAX_RETRIES,)).fetchall()
        for row in exhausted:
            timestamp = now()
            db.execute("UPDATE jobs SET status='discarded',active=0,retry_at='',updated_at=? WHERE id=?",
                       (timestamp, row["id"]))
            db.execute("INSERT INTO events(created_at,job_id,message) VALUES (?,?,?)",
                       (timestamp, row["id"], f"Noticia descartada automáticamente: límite de {MAX_RETRIES} reintentos agotado. "
                        + row["error"][:500]))
        if exhausted:
            db.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-500 FROM events)")

    def state(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        with self.connect() as db:
            db.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value, ensure_ascii=False)))

    def event(self, message, job_id=None):
        with self.connect() as db:
            db.execute("INSERT INTO events(created_at,job_id,message) VALUES (?,?,?)", (now(), job_id, message))
            db.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-500 FROM events)")

    def events(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 40")]

    @staticmethod
    def decode(row):
        if row is None:
            return None
        value = dict(row)
        for key in ["article", "work", "result"]:
            value[key] = json.loads(value[key]) if value[key] else None
        return value

    def get(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def jobs(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("""SELECT * FROM jobs ORDER BY
                CASE WHEN status='running' THEN 0 WHEN status IN ('queued','retry') THEN 1
                     WHEN status='discarded' THEN 2 WHEN status='waiting' THEN 3 ELSE 4 END,
                CASE WHEN queue_rank IS NULL THEN 1 ELSE 0 END,queue_rank,published_at DESC,id LIMIT 100""")]

    def playlist(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs WHERE active=1 AND status='ready' ORDER BY published_at DESC,id")]

    def inventory(self):
        with self.connect() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status")}
            counts["on_air"] = db.execute("SELECT COUNT(*) FROM jobs WHERE active=1 AND status='ready'").fetchone()[0]
            return counts

    @staticmethod
    def _record_publication(db, job, timestamp):
        identity = balancing.source(job)
        db.execute("INSERT OR IGNORE INTO source_publications VALUES (?,?,?,?,?)",
                   (job["id"], identity["id"], identity["name"], identity["platform"], timestamp))

    @staticmethod
    def _published_counts(db):
        return {row[0]: row[1] for row in db.execute(
            "SELECT source_id,COUNT(*) FROM source_publications GROUP BY source_id")}

    @staticmethod
    def _active(db):
        return [Store.decode(row) for row in db.execute("SELECT * FROM jobs WHERE active=1 AND status='ready'")]

    def source_balance(self, settings):
        with self.connect() as db:
            db.execute("BEGIN")
            published = self._published_counts(db)
            sources = {}
            catalog = db.execute("SELECT value FROM state WHERE key='balance_sources'").fetchone()
            for item in json.loads(catalog[0]) if catalog else []:
                sources[item["id"]] = {**item, "published": published.get(item["id"], 0),
                                       "on_air": 0, "pending": 0, "waiting": 0}
            for row in db.execute("SELECT source_id,source_name,platform FROM source_publications GROUP BY source_id"):
                sources.setdefault(row["source_id"], {"id": row["source_id"], "name": row["source_name"],
                    "platform": row["platform"], "published": published[row["source_id"]],
                    "on_air": 0, "pending": 0, "waiting": 0})
            for row in db.execute("SELECT * FROM jobs WHERE active=1 OR status IN ('running','queued','retry','waiting')"):
                job = self.decode(row)
                identity = balancing.source(job)
                entry = sources.setdefault(identity["id"], {**identity, "published": published.get(identity["id"], 0),
                                                            "on_air": 0, "pending": 0, "waiting": 0})
                entry["on_air"] += int(bool(job["active"]) and job["status"] == "ready")
                entry["pending"] += int(job["status"] in {"running", "queued", "retry"})
                entry["waiting"] += int(job["status"] == "waiting")
            initialized = db.execute("SELECT value FROM state WHERE key='source_history_initialized_at'").fetchone()
        return {"strategy": settings["balancing"]["strategy"], "description": balancing.policy(settings).description,
                "total_published": sum(published.values()), "initialized_at": json.loads(initialized[0]),
                "sources": sorted(({**entry, "weight": settings["balancing"]["weights"].get(entry["id"], 1)}
                                   for entry in sources.values()), key=lambda entry: (entry["published"], entry["name"]))}

    def admits(self, job, settings):
        with self.connect() as db:
            db.execute("BEGIN")
            return balancing.admits(job, self._active(db), self._published_counts(db), settings)

    @staticmethod
    def _rotation(db, settings):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        publications = [row[0] for row in db.execute(
            "SELECT recorded_at FROM source_publications WHERE recorded_at>? ORDER BY recorded_at", (cutoff,))]
        last = db.execute("""SELECT p.recorded_at,j.work FROM source_publications p
            JOIN jobs j ON j.id=p.job_id ORDER BY p.recorded_at DESC,p.job_id DESC LIMIT 1""").fetchone()
        started = (json.loads(last["work"]).get("production_started_at") or last["recorded_at"]) if last else None
        return rotation.plan(settings["new_stories_per_hour"], publications, started)

    def rotation(self, settings):
        with self.connect() as db:
            db.execute("BEGIN")
            return self._rotation(db, settings)

    def discover(self, articles, settings):
        inserted = 0
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for article in articles:
                count = db.execute("INSERT OR IGNORE INTO jobs(id,article_id,published_at,created_at,updated_at,article,retry_at,title_key,content_key,status) VALUES (?,?,?,?,?,?,?,?,?,'waiting')",
                                   (event_key(article), article["id"], article["published_at"], now(), now(),
                                    json.dumps(article, ensure_ascii=False), now(), title_key(article["title"]), content_key(article))).rowcount
                inserted += count
                # The old global date cutoff also rejected unused candidates.
                # Under fair selection only those never-started rows may return
                # to the reservoir. Processed, failed and retired clips remain
                # tombstones. The caller holds media_lock during discovery.
                if not count and settings["balancing"]["strategy"] == "fair":
                    db.execute("""UPDATE jobs SET status='waiting',stage='waiting',retry_at=?,updated_at=?,
                        artifacts_deleted_at=NULL,tts_deleted_at=NULL,queue_rank=NULL
                        WHERE id=? AND status='superseded' AND active=0 AND result IS NULL
                        AND work='{}' AND failures=0 AND error=''""", (now(), now(), event_key(article)))
            self._trim(db, settings)
        return inserted

    @staticmethod
    def _trim(db, settings):
        Store._discard_exhausted(db)
        published = Store._published_counts(db)
        active = Store._active(db)
        if len(active) > settings["max_playlist"]:
            keep = {job["id"] for job in balancing.keep(active, published, settings)}
            for job in active:
                if job["id"] not in keep:
                    db.execute("UPDATE jobs SET active=0 WHERE id=?", (job["id"],))
            active = [job for job in active if job["id"] in keep]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings["max_age_hours"])).isoformat()
        db.execute("UPDATE jobs SET status='superseded', stage='superseded' WHERE status IN ('queued','retry','waiting') AND published_at < ?", (cutoff,))
        running = [Store.decode(row) for row in db.execute("SELECT * FROM jobs WHERE status='running'")]
        slots = max(0, settings["max_pending"] - len(running))
        candidates = [Store.decode(row) for row in db.execute("""SELECT * FROM jobs
            WHERE status IN ('queued','waiting','retry') AND retry_at<=?""", (now(),))]
        # Voice work already started in another backend waits for that engine
        # to be selected again. It must not hold up the currently enabled one.
        candidates = [job for job in candidates if narration.engine(job["work"], settings) == settings["tts_engine"]]
        pending = balancing.select(candidates, published, running, active, slots, settings)
        db.execute("UPDATE jobs SET queue_rank=NULL WHERE status!='running'")
        db.execute("UPDATE jobs SET status='waiting' WHERE status='queued'")
        for rank, job in enumerate(pending):
            status = "retry" if job["status"] == "retry" else "queued"
            db.execute("UPDATE jobs SET status=?,queue_rank=? WHERE id=?", (status, rank, job["id"]))

    def claim(self, settings):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._trim(db, settings)
            if not self._rotation(db, settings)["can_start"]:
                return None
            row = db.execute("""SELECT * FROM jobs WHERE status IN ('queued','retry') AND retry_at<=?
                AND queue_rank IS NOT NULL ORDER BY queue_rank,id LIMIT 1""", (now(),)).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (now(), row["id"]))
            return self.decode(row)

    def skip(self, job_id, reason):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='superseded',error=?,updated_at=? WHERE id=? AND status='running'",
                       (reason, now(), job_id))

    def publication(self, job_id, article, published_at):
        with self.connect() as db:
            db.execute("UPDATE jobs SET published_at=?,article=?,updated_at=? WHERE id=? AND status='running'",
                       (published_at, json.dumps(article, ensure_ascii=False), now(), job_id))

    def progress(self, job_id, stage, work):
        with self.connect() as db:
            db.execute("UPDATE jobs SET stage=?,work=?,updated_at=? WHERE id=?",
                       (stage, json.dumps(work, ensure_ascii=False), now(), job_id))

    def retry(self, job_id, error, busy=False):
        with self.connect() as db:
            row = db.execute("SELECT status,failures FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["status"] != "running":
                return row["status"] if row else None
            failures = row["failures"] + (0 if busy else 1)
            if not busy and failures > MAX_RETRIES:
                db.execute("UPDATE jobs SET status='discarded',active=0,error=?,failures=?,retry_at='',updated_at=? WHERE id=?",
                           (error[:1500], failures, now(), job_id))
                return "discarded"
            delay = 30 if busy else min(3600, 60 * 2 ** min(failures, 6))
            db.execute("UPDATE jobs SET status='retry',error=?,failures=?,retry_at=?,updated_at=? WHERE id=?",
                       (error[:1500], failures, after(delay), now(), job_id))
            return "retry"

    def publish(self, job_id, result, settings):
        # A completed clip and replacement enter the playlist in one transaction.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if not job or job["status"] != "running":
                raise RuntimeError("El trabajo no está en producción; no se publica ni se vuelve a contabilizar.")
            published = self._published_counts(db)
            source_id = balancing.source(job)["id"]
            published[source_id] = published.get(source_id, 0) + 1
            active = [item for item in self._active(db) if item["id"] != job_id]
            keep = {item["id"] for item in balancing.keep(active + [job], published, settings)}
            admitted = job_id in keep
            db.execute("UPDATE jobs SET status='ready',stage='ready',active=?,result=?,error='',updated_at=?,queue_rank=NULL,artifacts_deleted_at=NULL,tts_deleted_at=NULL WHERE id=?",
                       (int(admitted), json.dumps(result, ensure_ascii=False), now(), job_id))
            if admitted:
                self._record_publication(db, job, now())
            for previous in active:
                if previous["id"] not in keep:
                    db.execute("UPDATE jobs SET active=0 WHERE id=?", (previous["id"],))
            self._trim(db, settings)
            return admitted

    def update_presentation(self, job_id, result):
        with self.connect() as db:
            db.execute("UPDATE jobs SET result=?,updated_at=? WHERE id=? AND status='ready'",
                       (json.dumps(result, ensure_ascii=False), now(), job_id))

    def release(self, job_id):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued',updated_at=? WHERE id=? AND status='running'", (now(), job_id))

    def retired_artifacts(self):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("""SELECT * FROM jobs
                WHERE active=0 AND status IN ('ready','superseded','discarded')
                  AND (artifacts_deleted_at IS NULL OR tts_deleted_at IS NULL)
                ORDER BY updated_at,id""")]

    def artifacts_deleted(self, job_id):
        with self.connect() as db:
            db.execute("UPDATE jobs SET artifacts_deleted_at=COALESCE(artifacts_deleted_at,?) WHERE id=?", (now(), job_id))

    def tts_deleted(self, job_id):
        with self.connect() as db:
            db.execute("UPDATE jobs SET tts_deleted_at=? WHERE id=?", (now(), job_id))
