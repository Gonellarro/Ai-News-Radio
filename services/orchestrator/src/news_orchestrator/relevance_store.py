"""Persistence and hourly budget for optional editorial evaluations."""

from datetime import datetime, timedelta, timezone
import json
from collections import defaultdict, deque

from news_orchestrator import relevance_policy as policy


def timestamp(seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class Repository:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS relevance_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, started_at TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS relevance_attempts_time ON relevance_attempts(started_at)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(relevance_attempts)")}
            if "origin" not in columns:
                db.execute("ALTER TABLE relevance_attempts ADD COLUMN origin TEXT NOT NULL DEFAULT 'automatic'")
            db.execute("""UPDATE jobs SET relevance=json_set(relevance,'$.status','error',
                '$.error','Valoración interrumpida; se reintentará respetando el presupuesto horario.')
                WHERE json_extract(relevance,'$.status')='evaluating'""")

    def budget(self, settings):
        with self.store.connect() as db:
            starts = [row[0] for row in db.execute("""SELECT started_at FROM relevance_attempts
                WHERE origin='automatic' AND started_at>? ORDER BY started_at""", (timestamp(-3600),))]
            manual = db.execute("SELECT COUNT(*) FROM relevance_attempts WHERE origin='manual' AND started_at>?", (timestamp(-3600),)).fetchone()[0]
        remaining = max(0, settings["relevance"]["max_evaluations_per_hour"] - len(starts))
        available_at = None
        if not remaining and starts:
            index = max(0, len(starts) - settings["relevance"]["max_evaluations_per_hour"])
            available_at = (datetime.fromisoformat(starts[index]) + timedelta(seconds=3601)).isoformat()
        return {"remaining_this_hour": remaining, "automatic_available_at": available_at,
                "manual_evaluations_last_hour": manual}

    def remaining(self, settings):
        return self.budget(settings)["remaining_this_hour"]

    def manual_scope(self):
        """Snapshot only the current playlist and scheduled production work."""
        with self.store.connect() as db:
            return [self.store.decode(row) for row in db.execute("""SELECT * FROM jobs WHERE manual_excluded=0
                AND (active=1 OR status='running' OR (status IN ('queued','retry') AND queue_rank IS NOT NULL))
                ORDER BY active DESC,published_at DESC,id""")]

    def pending(self, settings):
        cutoff = timestamp(-settings["max_age_hours"] * 3600)
        with self.store.connect() as db:
            jobs = [self.store.decode(row) for row in db.execute("""SELECT * FROM jobs
                WHERE (active=1 OR status IN ('queued','retry','waiting')) AND manual_excluded=0
                AND published_at>=? ORDER BY published_at DESC,id""", (cutoff,))]
        groups = defaultdict(deque)
        for job in jobs:
            value = policy.current(job, settings)
            if value.get("status") == "ready" or value.get("attempts", 0) >= 3 or value.get("retry_at", "") > timestamp():
                continue
            # Sample all three groups and sources, rather than evaluating the
            # entire reservoir or letting a prolific social feed monopolize it.
            group = "pending" if job["status"] in ("queued", "retry") else "active" if job["active"] else "reserve"
            groups[(group, job["article"].get("source_id", "unknown"))].append(job)
        queues = {group: deque(key for key in groups if key[0] == group) for group in ("pending", "active", "reserve")}
        result = []
        while any(queues.values()):
            for queue in queues.values():
                if queue:
                    key = queue.popleft()
                    result.append(groups[key].popleft())
                    if groups[key]:
                        queue.append(key)
        return result

    def begin(self, jobs, settings, manual=False):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM relevance_attempts WHERE started_at<?", (timestamp(-7*86400),))
            used = db.execute("SELECT COUNT(*) FROM relevance_attempts WHERE origin='automatic' AND started_at>?", (timestamp(-3600),)).fetchone()[0]
            if not manual and used + len(jobs) > settings["relevance"]["max_evaluations_per_hour"]:
                return []
            attempts = []
            for job in jobs:
                previous = policy.current(job, settings)
                value = {"fingerprint": policy.fingerprint(job, settings), "status": "evaluating",
                         "attempts": previous.get("attempts", 0) + int(not manual), "retry_at": timestamp(3600),
                         "manual_attempts": previous.get("manual_attempts", 0) + int(manual),
                         "evaluated_at": timestamp(), "origin": "manual" if manual else "automatic"}
                saved = policy.last_success(job.get("relevance") or {})
                if saved:
                    value["previous"] = saved
                db.execute("UPDATE jobs SET relevance=? WHERE id=?", (json.dumps(value), job["id"]))
                cursor = db.execute("INSERT INTO relevance_attempts(job_id,started_at,origin) VALUES (?,?,?)",
                                    (job["id"], timestamp(), "manual" if manual else "automatic"))
                attempts.append(cursor.lastrowid)
        return attempts

    def busy(self, jobs, attempts):
        with self.store.connect() as db:
            for job, attempt in zip(jobs, attempts):
                # A refusal before inference consumes neither the retry count
                # nor the hourly budget. Restore the previous cache as-is.
                db.execute("UPDATE jobs SET relevance=? WHERE id=?", (json.dumps(job.get("relevance") or {}), job["id"]))
                db.execute("DELETE FROM relevance_attempts WHERE id=?", (attempt,))

    def finish(self, jobs, settings, response=None, error=""):
        evaluations = {entry["id"]: entry for entry in response["evaluations"]} if response else {}
        if response and set(evaluations) != {job["article_id"] for job in jobs}:
            raise ValueError("La valoración no contiene las noticias solicitadas.")
        with self.store.connect() as db:
            for job in jobs:
                row = db.execute("SELECT relevance FROM jobs WHERE id=?", (job["id"],)).fetchone()
                if not row:
                    continue
                value = json.loads(row[0])
                value.update(status="error" if error else "ready", evaluated_at=timestamp(), error=error[:500])
                if response:
                    entry = evaluations[job["article_id"]]
                    scores = entry.get("scores")
                    if (not isinstance(scores, dict) or set(scores) != set(policy.DIMENSIONS)
                            or any(type(v) is not int or not 0 <= v <= 100 for v in scores.values())
                            or not isinstance(entry.get("reason"), str)):
                        raise ValueError("Puntuaciones editoriales no válidas.")
                    value.update(scores=scores, reason=entry["reason"][:500], model=response.get("model", ""))
                    value.pop("previous", None)
                db.execute("UPDATE jobs SET relevance=? WHERE id=?", (json.dumps(value, ensure_ascii=False), job["id"]))

    def page(self, settings, params):
        page = int(params.get("page", ["1"])[0])
        limit = int(params.get("limit", ["6"])[0])
        if not 1 <= page <= 100000 or not 1 <= limit <= 50:
            raise ValueError("Paginación de valoraciones no válida.")
        with self.store.connect() as db:
            jobs = [self.store.decode(row) for row in db.execute("""SELECT * FROM jobs
                WHERE active=1 OR status IN ('queued','retry','waiting','running') ORDER BY published_at DESC,id""")]
        rows = []
        valid, stale = 0, 0
        for job in jobs:
            value = policy.current(job, settings)
            score = policy.score(job, settings)
            valid += int(score is not None)
            previous = policy.last_success(job.get("relevance") or {}) if score is None else {}
            stale += int(bool(previous))
            rows.append({"id": job["id"], "title": job["article"]["title"], "source": job["article"].get("source_name", ""),
                         "status": "En parrilla" if job["active"] else {"queued": "En cola", "retry": "Reintento",
                             "waiting": "En reserva", "running": "En producción"}.get(job["status"], job["status"]), "score": score,
                         "evaluation": value or {"status": "pending"}, "stale": bool(previous),
                         "previous_score": policy.weighted_score(previous, settings) if previous else None,
                         "previous_evaluation": previous})
        rows.sort(key=lambda row: (0 if row["score"] is not None else 1 if row["stale"] else 2,
                                  -(row["score"] if row["score"] is not None else row["previous_score"] or 0)))
        return {"rows": rows[(page-1)*limit:page*limit], "total": len(rows), "evaluated": valid,
                "stale": stale, **self.budget(settings), "next_at": self.store.state("next_relevance_at"),
                "error": self.store.state("relevance_error", ""), "last_at": self.store.state("last_relevance_at")}
