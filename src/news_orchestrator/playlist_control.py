"""Manual scheduling, independent of discovery, rendering and selection policy."""

import hashlib
import json
import re
from datetime import datetime, timezone, timedelta

from news_orchestrator import config, lifetime
from news_orchestrator.store import Store, now


class Conflict(ValueError):
    pass


def state(db, key, default=None):
    row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db, key, value):
    db.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, ensure_ascii=False)))


def ordered(db):
    jobs = [Store.decode(row) for row in db.execute(
        "SELECT * FROM jobs WHERE active=1 AND status='ready' ORDER BY published_at DESC,id")]
    if state(db, "playlist_mode", "automatic") == "manual":
        positions = {job_id: i for i, job_id in enumerate(state(db, "playlist_order", []))}
        jobs.sort(key=lambda job: positions.get(job["id"], len(positions)))
    return jobs


def snapshot(db):
    jobs = ordered(db)
    mode = state(db, "playlist_mode", "automatic")
    body = {"ids": [job["id"] for job in jobs], "pinned": [job["id"] for job in jobs if job["pinned"]],
            "mode": mode, "next_id": state(db, "next_play_id")}
    revision = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {**body, "revision": revision, "jobs": jobs, "next_id": state(db, "next_play_id"),
            "playing_id": state(db, "playing_id")}


class Playlist:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.store = pipeline.store

    def get(self):
        with self.store.connect() as db:
            db.execute("BEGIN")
            return snapshot(db)

    def save(self, payload):
        ids, pinned = payload.get("ids"), payload.get("pinned")
        if (not isinstance(ids, list) or not isinstance(pinned, list)
                or any(not isinstance(i, str) or not re.fullmatch(r"[a-f0-9]{64}", i) for i in ids + pinned)
                or len(ids) != len(set(ids)) or len(pinned) != len(set(pinned))
                or not set(pinned) <= set(ids) or payload.get("mode") not in {"manual", "automatic"}):
            raise ValueError("La parrilla debe contener noticias únicas y un modo válido.")
        next_id = payload.get("next_id")
        if next_id is not None and next_id not in ids:
            raise ValueError("La próxima noticia debe pertenecer a la parrilla.")
        with self.pipeline.media_lock, lifetime.locked(), config.WRITE_LOCK:
            settings = config.load()
            if len(ids) > settings["max_playlist"]:
                raise ValueError(f"La parrilla admite hasta {settings['max_playlist']} noticias.")
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = snapshot(db)
                if payload.get("revision") != current["revision"]:
                    raise Conflict("La parrilla ha cambiado. Recárgala antes de guardar tus cambios.")
                jobs = {}
                for job_id in ids:
                    job = Store.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
                    folder = config.DATA / "media" / job_id
                    if not job or job["status"] != "ready" or job["artifacts_deleted_at"] or not (folder / "video.mp4").is_file():
                        raise ValueError("Solo se pueden incorporar noticias con vídeo disponible.")
                    jobs[job_id] = job
                for job_id in set(current["ids"]) - set(ids):
                    db.execute("UPDATE jobs SET active=0,pinned=0,manual_excluded=1 WHERE id=?", (job_id,))
                for job_id, job in jobs.items():
                    db.execute("UPDATE jobs SET active=1,pinned=?,manual_excluded=0 WHERE id=?", (int(job_id in pinned), job_id))
                    if job_id not in current["ids"]:
                        db.execute("UPDATE jobs SET playlist_entered_at=? WHERE id=?", (now(), job_id))
                        self.store._record_publication(db, job, now())
                put(db, "playlist_mode", payload["mode"])
                put(db, "playlist_order", ids)
                put(db, "next_play_id", next_id)
                db.execute("INSERT INTO events(created_at,message) VALUES (?,?)",
                           (now(), f"Parrilla editada: {len(ids)} noticias, {len(pinned)} fijadas; orden {payload['mode']}."))
                result = snapshot(db)
        return result

    def request(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
            raise ValueError("Selecciona una noticia de la biblioteca.")
        with self.pipeline.media_lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = Store.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if not job or job["status"] not in {"waiting", "queued", "retry"}:
                raise ValueError("Solo se pueden solicitar candidatas o trabajos pendientes.")
            cutoff = datetime.now(timezone.utc) - timedelta(hours=config.load()["max_age_hours"])
            if datetime.fromisoformat(job["published_at"]) < cutoff:
                raise ValueError("La noticia supera la antigüedad máxima configurada.")
            db.execute("UPDATE jobs SET requested=1,manual_excluded=0 WHERE id=?", (job_id,))
            self.store._trim(db, config.load())
        self.store.event("Noticia solicitada para producción; tendrá prioridad en el lote de actualización disponible.", job_id)
        return {"requested": job_id}


def library(store, params):
    page = int(params.get("page", ["1"])[0])
    limit = int(params.get("limit", ["6"])[0])
    if not 1 <= page <= 100000 or not 1 <= limit <= 50:
        raise ValueError("Paginación no válida.")
    mode = params.get("filter", ["on_air"])[0]
    filters = {"on_air": "active=1 AND status='ready'", "pending": "status IN ('running','queued','retry')",
               "waiting": "status='waiting'", "ready": "status='ready' AND artifacts_deleted_at IS NULL",
               "discarded": "status='discarded'", "all": "1=1"}
    if mode not in filters:
        raise ValueError("Filtro de noticias no válido.")
    where, values = filters[mode], []
    query = params.get("q", [""])[0].strip()
    if len(query) > 300:
        raise ValueError("La búsqueda admite hasta 300 caracteres.")
    if query:
        where += " AND (json_extract(article,'$.title') LIKE ? OR json_extract(result,'$.title') LIKE ? OR json_extract(article,'$.source_name') LIKE ?)"
        values = [f"%{query}%"] * 3
    with store.connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT COUNT(*) FROM jobs WHERE " + where, values).fetchone()[0]
        jobs = [Store.decode(row) for row in db.execute("SELECT * FROM jobs WHERE " + where +
            " ORDER BY CASE WHEN status='running' THEN 0 ELSE 1 END,published_at DESC,id LIMIT ? OFFSET ?",
            values + [limit, (page-1)*limit])]
    return {"jobs": jobs, "total": total, "page": page, "limit": limit}
