"""Remove retired news media, retaining the small history used for deduplication."""

import logging
import re
import shutil

from news_orchestrator import config, lifetime
from news_orchestrator.store import now


def cleanup(store, tts, media_lock, stop):
    removed, purged = 0, 0
    remote = []
    for candidate in store.retired_artifacts():
        if stop.is_set():
            raise InterruptedError()
        job_id = candidate["id"]
        if not re.fullmatch(r"[a-f0-9]{64}", job_id):
            raise RuntimeError("Identificador de noticia no válido durante la limpieza.")
        # The thread lock protects a presentation rebuild; the process lock
        # protects the broadcaster choosing its next clip and claiming it.
        with media_lock:
            with lifetime.locked():
                job = store.get(job_id)
                if (not job or job["active"] or job["status"] not in {"ready", "superseded", "discarded"}
                        or store.state("playing_id") == job_id):
                    continue
                directory = config.DATA / "media" / job_id
                trash = directory.with_name(".retired-" + job_id)
                if directory.is_symlink() or trash.is_symlink():
                    raise RuntimeError("Se ha encontrado un enlace inesperado en los archivos de una noticia retirada.")
                if directory.exists():
                    if trash.exists():
                        raise RuntimeError("Hay dos carpetas pendientes de retirar para la misma noticia.")
                    directory.rename(trash)
            # Once moved, no reader can select it. Keep slow deletion/network
            # work outside the broadcaster lock. Hardlinked live HLS survives.
            if trash.exists():
                shutil.rmtree(trash)
                removed += 1
            store.artifacts_deleted(job_id)
        if not job.get("tts_deleted_at"):
            remote.append(job)
    # Finish all local retirements even when Qwen is offline. Remote audio is
    # retried on the next sweep without affecting production retry counters.
    pending = 0
    for job in remote:
        if stop.is_set():
            raise InterruptedError()
        job_id, work = job["id"], job["work"]
        if work.get("voice_id") or work.get("tts_id") or work.get("tts_generation"):
            try:
                result = tts.request("/api/jobs/purge-news", {"story_id": job_id}, timeout=15)
            except Exception:
                if removed or purged:
                    store.event(f"Limpieza local completada: {removed} carpetas retiradas; pendiente de recuperar la conexión con Qwen para terminar su limpieza.")
                raise
            purged += result["purged_count"]
            if result["pending"]:
                pending += len(result["pending"])
                continue  # An old remote attempt may still be finishing.
        store.tts_deleted(job_id)
    store.set_state("last_cleanup_at", now())
    if removed or purged:
        store.event(f"Limpieza automática: {removed} carpetas de noticias retiradas y {purged} trabajos de audio de Qwen eliminados. Se conserva el historial.")
    return {"removed_folders": removed, "purged_tts_jobs": purged, "pending_tts_jobs": pending}


def run(store, tts, media_lock, stop):
    while not stop.is_set():
        try:
            result = cleanup(store, tts, media_lock, stop)
            store.set_state("cleanup_error", "")
            store.set_state("last_cleanup_result", result)
        except InterruptedError:
            return
        except Exception as exc:
            logging.exception("Retired news cleanup failed")
            store.set_state("cleanup_error", str(exc)[:1500])
        stop.wait(30)
