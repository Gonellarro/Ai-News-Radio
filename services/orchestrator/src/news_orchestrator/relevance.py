"""Editorial evaluator with manual priority at complete production boundaries."""

import logging
import sqlite3
import threading
import uuid

from news_orchestrator import config
from news_orchestrator import relevance_policy as policy
from news_orchestrator.relevance_store import Repository, timestamp
from news_orchestrator.client import RemoteError

MANUAL_PENDING = {"queued", "waiting_production", "waiting_ai", "running"}
MANUAL_STATE = "manual_relevance_request"


class Evaluator:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.repository = Repository(pipeline.store)
        self.requested = threading.Event()  # Automatic wake-up only; never bypasses its budget.
        self.active = False
        self.batch_ids = []
        request = self.manual_request()
        if request.get("status") in MANUAL_PENDING:
            self._save_manual({**request, "status": "queued", "batch_ids": [], "retry_at": ""})

    def manual_request(self):
        return self.pipeline.store.state(MANUAL_STATE, {})

    def _save_manual(self, request):
        self.pipeline.store.set_state(MANUAL_STATE, request)

    def blocks_production(self):
        # Caller holds activity_lock. A pending request reserves the NEXT whole
        # production slot; it never interrupts Pipeline.produce in flight.
        return self.active or self.manual_request().get("status") in MANUAL_PENDING

    def request_manual(self):
        with self.pipeline.activity_lock:
            settings = config.load()
            if settings["relevance"]["mode"] == "off":
                raise ValueError("Activa observación o selección antes de valorar noticias.")
            existing = self.manual_request()
            if existing.get("status") in MANUAL_PENDING:
                return {"scheduled": True, "duplicate": True, "manual": existing,
                        "message": "Ya hay una valoración manual pendiente o en curso; no se duplica."}
            # Valid cached judgements are reused. Manual intervention also lets
            # failed/stale items be tried once, without the automatic retry delay.
            jobs = [job for job in self.repository.manual_scope() if policy.score(job, settings) is None]
            request = {"id": uuid.uuid4().hex, "requested_at": timestamp(),
                       "criteria_key": policy.criteria_key(settings), "job_ids": [job["id"] for job in jobs],
                       "completed_ids": [], "failed_ids": [], "skipped_ids": [],
                       "status": "queued" if jobs else "done", "total": len(jobs), "batch_ids": [], "retry_at": ""}
            if not jobs:
                request.update(finished_at=timestamp(), message="La parrilla y los trabajos programados ya están valorados con los criterios actuales.")
            elif self.pipeline.active_id:
                request.update(status="waiting_production", message="Resumen/generación de voz en curso. La valoración empezará cuando termine la producción completa de esta noticia, incluido el vídeo.")
            else:
                request["message"] = "Valoración manual en cola prioritaria; omite el límite horario automático."
            self._save_manual(request)
        if jobs:
            self.pipeline.store.event(f"Valoración manual solicitada para {len(jobs)} noticias de parrilla y producción; prioridad al terminar la noticia en curso.")
        return {"scheduled": bool(jobs), "manual": request, "message": request["message"]}

    def run(self):
        stop, store = self.pipeline.stop, self.pipeline.store
        while not stop.is_set():
            try:
                settings = config.load()
                request = self.manual_request()
                if settings["relevance"]["mode"] == "off":
                    self.requested.clear()
                    if request.get("status") in MANUAL_PENDING:
                        with self.pipeline.activity_lock:
                            self._save_manual({**request, "status": "cancelled", "finished_at": timestamp(),
                                               "message": "Valoración cancelada al desactivar el módulo."})
                elif request.get("status") in MANUAL_PENDING:
                    self.manual_step(settings)
                elif settings["enabled"] and (self.requested.is_set() or store.state("next_relevance_at", "") <= timestamp()):
                    cycle = store.cycle()
                    if cycle and cycle["status"] in {"ready", "producing"}:
                        self.requested.clear()
                        self.automatic_cycle(settings)
            except Exception as exc:
                logging.exception("Editorial relevance evaluation failed")
                store.report_error("relevance_error", exc)
                try:
                    store.set_state("next_relevance_at", timestamp(300))
                    with self.pipeline.activity_lock:
                        request = self.manual_request()
                        if request.get("status") == "running":
                            self._save_manual({**request, "status": "error", "finished_at": timestamp(),
                                               "message": "No se pudo completar la valoración manual: " + str(exc)[:350]})
                except sqlite3.Error:
                    logging.exception("Could not persist failed evaluation")
            stop.wait(2)

    @staticmethod
    def batch_size(settings):
        return min(4, max(1, (7500 - len(settings["relevance"]["criteria"])) // 1600))

    def _batch(self, jobs, settings, manual=False):
        """Reserve the shared scheduler before touching the local model."""
        with self.pipeline.activity_lock:
            if self.pipeline.active_id or self.pipeline.stop.is_set():
                return "production"
            if not manual and self.manual_request().get("status") in MANUAL_PENDING:
                return "manual"
            attempts = self.repository.begin(jobs, settings, manual=manual)
            if not attempts:
                return "budget"
            self.active = True
            self.batch_ids = [job["id"] for job in jobs]
        try:
            result = self.pipeline.news.request("/api/editorial/relevance", {
                "topic": settings["topic"], "criteria": settings["relevance"]["criteria"],
                "articles": [policy.evidence(job) for job in jobs],
            }, timeout=330)
            self.repository.finish(jobs, settings, response=result)
            self.pipeline.store.set_state("relevance_error", "")
            self.pipeline.store.set_state("last_relevance_at", timestamp())
            self.pipeline.store.event(f"Relevancia editorial: {len(jobs)} extractos valorados; origen {'manual' if manual else 'automático'}.")
            return "done"
        except RemoteError as exc:
            if exc.status == 409:
                self.repository.busy(jobs, attempts)
                return "busy"
            self.repository.finish(jobs, settings, error=str(exc))
            raise
        except Exception as exc:
            self.repository.finish(jobs, settings, error=str(exc))
            raise
        finally:
            with self.pipeline.activity_lock:
                self.active = False
                self.batch_ids = []

    def manual_step(self, settings):
        with self.pipeline.activity_lock:
            request = self.manual_request()
            if request.get("status") not in MANUAL_PENDING:
                return
            if request["criteria_key"] != policy.criteria_key(settings):
                self._save_manual({**request, "status": "cancelled", "finished_at": timestamp(),
                    "message": "Los criterios cambiaron durante la petición. Pulsa Valorar ahora para usar los nuevos criterios."})
                return
            if self.pipeline.active_id:
                self._save_manual({**request, "status": "waiting_production",
                    "message": "Resumen/generación de voz en curso. Se espera al final de la noticia completa, incluido el vídeo."})
                return
            if request.get("retry_at", "") > timestamp():
                return
            processed = set(request["completed_ids"] + request["failed_ids"] + request["skipped_ids"])
            batch = []
            for job_id in request["job_ids"]:
                if job_id in processed:
                    continue
                job = self.pipeline.store.get(job_id)
                in_scope = job and (job["active"] or job["status"] == "running" or
                                   (job["status"] in {"queued", "retry"} and job.get("queue_rank") is not None))
                if not in_scope or job.get("manual_excluded"):
                    request["skipped_ids"].append(job_id)
                elif policy.score(job, settings) is not None:
                    request["completed_ids"].append(job_id)
                else:
                    batch.append(job)
                if len(batch) >= self.batch_size(settings):
                    break
            if not batch:
                self._save_manual({**request, "status": "done", "finished_at": timestamp(), "batch_ids": [],
                    "message": f"Valoración manual finalizada: {len(request['completed_ids'])} valoradas y {len(request['skipped_ids'])} omitidas."})
                return
            request.update(status="running", batch_ids=[job["id"] for job in batch], message="Gemma está valorando la petición manual prioritaria.")
            self._save_manual(request)
        try:
            outcome = self._batch(batch, settings, manual=True)
        except Exception as exc:
            with self.pipeline.activity_lock:
                current = self.manual_request()
                self._save_manual({**current, "status": "error", "batch_ids": [], "finished_at": timestamp(),
                    "failed_ids": current["failed_ids"] + [job["id"] for job in batch],
                    "message": "Valoración manual detenida por un error; la producción automática puede continuar. " + str(exc)[:250]})
            raise
        with self.pipeline.activity_lock:
            current = self.manual_request()
            if outcome == "done":
                current.update(status="queued", batch_ids=[], retry_at="",
                               completed_ids=current["completed_ids"] + [job["id"] for job in batch],
                               message="Petición manual en curso; continúa con el siguiente lote.")
            else:
                current.update(status="waiting_production" if outcome == "production" else "waiting_ai",
                    batch_ids=[], retry_at=timestamp(15), message="Esperando al final de la producción completa de la noticia." if outcome == "production" else "La IA local está ocupada; la petición manual conserva su prioridad.")
            self._save_manual(current)

    def automatic_cycle(self, settings):
        cycle = self.pipeline.store.cycle()
        if not cycle or cycle["status"] not in {"ready", "producing"}:
            return
        budget = self.repository.budget(settings)
        if not budget["remaining_this_hour"]:
            self.pipeline.store.set_state("next_relevance_at", budget["automatic_available_at"] or timestamp(60))
            return
        jobs = self.repository.pending(settings)[:budget["remaining_this_hour"]]
        self.pipeline.store.set_state("next_relevance_at", timestamp(settings["relevance"]["interval_seconds"]))
        size = self.batch_size(settings)
        for offset in range(0, len(jobs), size):
            latest = config.load()
            current_cycle = self.pipeline.store.cycle()
            if (self.pipeline.stop.is_set() or latest["relevance"]["mode"] == "off"
                    or not current_cycle or current_cycle["id"] != cycle["id"]
                    or current_cycle["status"] not in {"ready", "producing"}
                    or any(policy.fingerprint(j, settings) != policy.fingerprint(j, latest) for j in jobs[offset:offset+size])):
                return
            # Re-read cache after each batch so busy rollback never restores an
            # older value over a judgement produced by a previous request.
            batch = [self.pipeline.store.get(job["id"]) for job in jobs[offset:offset+size]]
            outcome = self._batch(batch, latest)
            if outcome != "done":
                self.pipeline.store.set_state("next_relevance_at", timestamp(30))
                return

    def info(self, params):
        settings = config.load()
        with self.pipeline.activity_lock:
            request = self.manual_request()
            production = self.pipeline.store.get(self.pipeline.active_id) if self.pipeline.active_id else None
            return {**self.repository.page(settings, params), "mode": settings["relevance"]["mode"],
                    "active": self.active, "batch_ids": list(self.batch_ids), "manual": request,
                    "production": {"id": production["id"], "title": production["article"]["title"],
                                   "stage": production["stage"]} if production else None}
