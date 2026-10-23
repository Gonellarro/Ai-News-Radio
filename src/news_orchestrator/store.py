from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import sqlite3
import unicodedata
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from news_orchestrator import balancing, narration, playlist_rotation, rotation

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
            for name in ("pinned", "manual_excluded", "requested"):
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
            if "relevance" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN relevance TEXT NOT NULL DEFAULT '{}'")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_content ON jobs(content_key) WHERE content_key IS NOT NULL")
            db.execute("""CREATE TABLE IF NOT EXISTS source_publications (
                job_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_name TEXT NOT NULL,
                platform TEXT NOT NULL, recorded_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS publications_by_source ON source_publications(source_id)")
            db.execute("CREATE INDEX IF NOT EXISTS publications_by_time ON source_publications(recorded_at)")
            db.execute("""CREATE TABLE IF NOT EXISTS production_cycles (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, scheduled_for TEXT,
                origin TEXT NOT NULL, quota INTEGER NOT NULL, status TEXT NOT NULL,
                finished_at TEXT, error TEXT NOT NULL DEFAULT '', retry_at TEXT NOT NULL DEFAULT ''
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS cycle_publications (
                job_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL, recorded_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS cycle_publications_cycle ON cycle_publications(cycle_id)")
            if "retry_at" not in {row["name"] for row in db.execute("PRAGMA table_info(production_cycles)")}:
                db.execute("ALTER TABLE production_cycles ADD COLUMN retry_at TEXT NOT NULL DEFAULT ''")
            # Backfill once, including retired clips whose media was removed.
            # Each clip counts once, never once per loop, retry or visual update.
            if not db.execute("SELECT 1 FROM state WHERE key='source_history_initialized_at'").fetchone():
                for row in db.execute("SELECT * FROM jobs WHERE status='ready'").fetchall():
                    self._record_publication(db, self.decode(row), row["updated_at"])
                db.execute("INSERT INTO state VALUES ('source_history_initialized_at',?)", (json.dumps(now()),))
            if "playlist_entered_at" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN playlist_entered_at TEXT")
                # Historical admission times are stable even when a card or
                # voice presentation has subsequently changed updated_at.
                db.execute("""UPDATE jobs SET playlist_entered_at=COALESCE(
                    (SELECT recorded_at FROM source_publications WHERE job_id=jobs.id),updated_at)
                    WHERE active=1""")

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

    def report_error(self, key, error):
        """A temporary write failure must not kill a background worker."""
        try:
            self.set_state(key, str(error)[:1500])
        except sqlite3.Error:
            logging.exception("Could not persist background error: %s", key)

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
        for key in ["article", "work", "result", "relevance"]:
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
            from news_orchestrator.playlist_control import ordered
            return ordered(db)

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
            return playlist_rotation.admits(job, self._active(db), settings["max_playlist"])

    @staticmethod
    def _rotation(db, settings):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        recent = db.execute("SELECT COUNT(*) FROM source_publications WHERE recorded_at>?", (cutoff,)).fetchone()[0]
        cycle = Store._cycle(db)
        published = db.execute("SELECT COUNT(*) FROM cycle_publications WHERE cycle_id=?", (cycle["id"],)).fetchone()[0] if cycle else 0
        deadline = db.execute("SELECT value FROM state WHERE key='next_scan_at'").fetchone()
        return rotation.plan(cycle, published, recent, json.loads(deadline[0]) if deadline else None,
                             default_quota=settings["new_stories_per_update"])

    @staticmethod
    def _cycle(db):
        row = db.execute("SELECT value FROM state WHERE key='production_cycle_id'").fetchone()
        cycle = db.execute("SELECT * FROM production_cycles WHERE id=?", (json.loads(row[0]),)).fetchone() if row else None
        return dict(cycle) if cycle else None

    def cycle(self):
        with self.connect() as db:
            return self._cycle(db)

    def start_cycle(self, settings, origin, scheduled_for=None):
        """Replace unstarted work from older updates; preserve running jobs."""
        cycle_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE production_cycles SET status='replaced',finished_at=? WHERE status IN ('collecting','ready','producing')", (now(),))
            db.execute("INSERT INTO production_cycles(id,started_at,scheduled_for,origin,quota,status) VALUES (?,?,?,?,?,'collecting')",
                       (cycle_id, now(), scheduled_for, origin, settings["new_stories_per_update"]))
            db.execute("INSERT INTO state VALUES ('production_cycle_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(cycle_id),))
        return cycle_id

    def finish_collection(self, cycle_id, settings, error=""):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE production_cycles SET status=?,error=? WHERE id=? AND status='collecting'",
                       ("error" if error else "ready", error[:1500], cycle_id))
            self._trim(db, settings)

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
                        AND work='{}' AND failures=0 AND error='' AND manual_excluded=0""", (now(), now(), event_key(article)))
            self._trim(db, settings)
        return inserted

    @staticmethod
    def _trim(db, settings):
        Store._discard_exhausted(db)
        published = Store._published_counts(db)
        active = Store._active(db)
        if len(active) > settings["max_playlist"]:
            keep = {job["id"] for job in playlist_rotation.keep(active, settings["max_playlist"])}
            for job in active:
                if job["id"] not in keep:
                    db.execute("UPDATE jobs SET active=0 WHERE id=?", (job["id"],))
            active = [job for job in active if job["id"] in keep]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings["max_age_hours"])).isoformat()
        db.execute("UPDATE jobs SET status='superseded', stage='superseded' WHERE status IN ('queued','retry','waiting') AND published_at < ?", (cutoff,))
        running = [Store.decode(row) for row in db.execute("SELECT * FROM jobs WHERE status='running'")]
        slots = max(0, settings["max_pending"] - len(running))
        candidates = [Store.decode(row) for row in db.execute("""SELECT * FROM jobs
            WHERE status IN ('queued','waiting','retry') AND manual_excluded=0 AND retry_at<=?""", (now(),))]
        # Voice work already started in another backend waits for that engine
        # to be selected again. It must not hold up the currently enabled one.
        candidates = [job for job in candidates if narration.engine(job["work"], settings) == settings["tts_engine"]]
        pending = balancing.select(candidates, published, running, active, slots, settings)
        db.execute("UPDATE jobs SET queue_rank=NULL WHERE status!='running'")
        db.execute("UPDATE jobs SET status='waiting' WHERE status='queued'")
        for rank, job in enumerate(pending):
            status = "retry" if job["status"] == "retry" else "queued"
            db.execute("UPDATE jobs SET status=?,queue_rank=? WHERE id=?", (status, rank, job["id"]))
        if pending:
            db.execute("""UPDATE production_cycles SET retry_at='' WHERE retry_at!=''
                AND id=(SELECT json_extract(value,'$') FROM state WHERE key='production_cycle_id')""")

    def claim(self, settings):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._trim(db, settings)
            allowance = self._rotation(db, settings)
            if not allowance["can_start"]:
                return None
            row = db.execute("""SELECT * FROM jobs WHERE status IN ('queued','retry') AND retry_at<=?
                AND queue_rank IS NOT NULL ORDER BY queue_rank,id LIMIT 1""", (now(),)).fetchone()
            if row:
                job = self.decode(row)
                job["work"]["production_cycle_id"] = allowance["cycle_id"]
                db.execute("UPDATE jobs SET status='running',work=?,updated_at=? WHERE id=?",
                           (json.dumps(job["work"], ensure_ascii=False), now(), job["id"]))
                db.execute("UPDATE production_cycles SET status='producing' WHERE id=? AND status='ready'", (allowance["cycle_id"],))
                return job
            # End an empty batch, or sleep until an actual retry is due, rather
            # than polling Qwen and rescanning all candidates every two seconds.
            active = self._active(db)
            future = [self.decode(item) for item in db.execute("""SELECT * FROM jobs
                WHERE status='retry' AND manual_excluded=0 AND retry_at>? AND published_at>=?""",
                (now(), (datetime.now(timezone.utc)-timedelta(hours=settings['max_age_hours'])).isoformat()))]
            future = [item for item in future if narration.engine(item['work'], settings) == settings['tts_engine']
                      and (balancing.resumable(item) or playlist_rotation.admits(item, active, settings["max_playlist"]))]
            if future:
                db.execute("UPDATE production_cycles SET retry_at=? WHERE id=?",
                           (min(item['retry_at'] for item in future), allowance['cycle_id']))
            else:
                db.execute("UPDATE production_cycles SET status='exhausted',finished_at=? WHERE id=?", (now(), allowance['cycle_id']))
            return None

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
            timestamp = now()
            job["playlist_entered_at"] = timestamp
            active = [item for item in self._active(db) if item["id"] != job_id]
            keep = {item["id"] for item in playlist_rotation.keep(active + [job], settings["max_playlist"])}
            admitted = job_id in keep
            db.execute("UPDATE jobs SET status='ready',stage='ready',active=?,result=?,error='',updated_at=?,playlist_entered_at=?,queue_rank=NULL,requested=0,artifacts_deleted_at=NULL,tts_deleted_at=NULL WHERE id=?",
                       (int(admitted), json.dumps(result, ensure_ascii=False), timestamp, timestamp if admitted else None, job_id))
            if admitted:
                self._record_publication(db, job, timestamp)
                cycle_id = job["work"].get("production_cycle_id")
                if cycle_id:
                    db.execute("INSERT OR IGNORE INTO cycle_publications VALUES (?,?,?)", (job_id, cycle_id, now()))
                    db.execute("""UPDATE production_cycles SET status='completed',finished_at=? WHERE id=?
                        AND status IN ('ready','producing') AND quota<=(SELECT COUNT(*) FROM cycle_publications WHERE cycle_id=?)""", (now(), cycle_id, cycle_id))
            for previous in active:
                if previous["id"] not in keep:
                    db.execute("UPDATE jobs SET active=0 WHERE id=?", (previous["id"],))
                    db.execute("INSERT INTO events(created_at,job_id,message) VALUES (?,?,?)",
                               (timestamp, previous["id"], "Renovación automática: se retira la noticia que llevaba más tiempo en parrilla. Sus archivos se borrarán al terminar su emisión."))
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
