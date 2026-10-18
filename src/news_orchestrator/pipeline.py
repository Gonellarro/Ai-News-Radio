"""Hourly discovery and serial automatic production. No approval states."""

from datetime import datetime, timedelta, timezone
import fcntl
import json
import logging
import os
import threading
import time

from news_orchestrator import config, discovery, intros, media, presentation, retention, visuals, youtube_control, voices as voice_selection
from news_orchestrator.client import Client, RemoteError
from news_orchestrator.store import MAX_RETRIES, Store, now, after


class Pipeline:
    def __init__(self):
        config.DATA.mkdir(parents=True, exist_ok=True)
        (config.DATA / "media").mkdir(exist_ok=True)
        self.instance = (config.DATA / "producer.lock").open("a+")
        try:
            fcntl.flock(self.instance, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Ya hay un orquestador utilizando esta base de datos.") from exc
        self.store = Store(config.DATA)
        self.store.recover()
        self.news = Client("NEWS_RADIO_URL", "http://127.0.0.1:8790")
        self.tts = Client("QWENTTS_URL", "http://127.0.0.1:8791")
        self.stop = threading.Event()
        self.requested = threading.Event()
        self.requested.set()  # Rebuild the reservoir from the library on startup.
        self.scanning = False
        self.active_id = None
        self.presentation_active_id = None
        self.media_lock = threading.Lock()
        self.threads = []

    def start(self):
        for name, method in [("discovery", self.discovery), ("production", self.production), ("presentation", self.presentations),
                             ("cleanup", self.cleanup)]:
            thread = threading.Thread(target=method, name=name, daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=3)

    def discovery(self):
        while not self.stop.is_set():
            try:
                settings = config.load()
                due = self.store.state("next_scan_at", "") <= now()
                if settings["enabled"] and (due or self.requested.is_set()):
                    self.requested.clear()
                    self.scanning = True
                    self.scan(settings)
                    self.store.set_state("next_scan_at", after(settings["scan_interval_seconds"]))
                self.store.set_state("configuration_error", "")
            except InterruptedError:
                break
            except Exception as exc:
                logging.exception("Discovery failed")
                self.store.set_state("scan_error", str(exc)[:1500])
                self.store.set_state("next_scan_at", after(300))
                self.store.event("No se pudo completar la recopilación; se reintentará: " + str(exc)[:500])
            finally:
                self.scanning = False
            self.stop.wait(2)

    def scan(self, settings):
        self.store.set_state("scan_started_at", now())
        self.store.event("Recopilación automática de noticias iniciada.")
        # Let production start from already saved material while remote sources
        # refresh; a slow search engine must not leave the producer idle.
        initial = discovery.candidates(self.news, settings, self.stop)
        with self.media_lock:
            count = self.store.discover(initial, settings)
        self.news.request("/api/refresh", {})
        deadline = time.monotonic() + 180
        while True:
            status = self.news.request("/api/sources")
            if not status.get("refreshing"):
                break
            if time.monotonic() >= deadline:
                self.store.event("Las fuentes siguen actualizándose; se utiliza la biblioteca disponible.")
                break
            if self.stop.wait(2):
                raise InterruptedError()
        articles = discovery.candidates(self.news, settings, self.stop)
        with self.media_lock:
            count += self.store.discover(articles, settings)
        self.store.set_state("balance_sources", [{"id": source["id"], "name": source["name"],
            "platform": source.get("platform", "web"), "enabled": source["enabled"],
            "available": source.get("available", False)} for source in status["sources"]])
        selected_sources = [s for s in status["sources"] if s["enabled"]
                            and (not settings["source_ids"] or s["id"] in settings["source_ids"])]
        warnings = [f"{s['name']}: {s.get('error') or 'sin vía de recogida activa'}" for s in selected_sources
                    if s.get("state") in {"error", "rate_limited", "missing_feed"}]
        self.store.set_state("source_warnings", warnings)
        self.store.set_state("last_scan_at", now())
        self.store.set_state("scan_error", "")
        recent = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        self.store.set_state("last_scan_count", {"found": len(articles), "new": count,
                                                "recent_24h": sum(a["published_at"] >= recent for a in articles)})
        self.store.event(f"Recopilación terminada: {len(articles)} candidatas, {count} nuevas incorporadas a la reserva. Selección de fuentes: {settings['balancing']['strategy']}.")

    def production(self):
        while not self.stop.is_set():
            job = None
            try:
                settings = config.load()
                if not settings["enabled"]:
                    self.stop.wait(2)
                    continue
                # Service outages do not consume or repeatedly submit queued work.
                self.news.request("/health", timeout=5)
                tts_status = self.tts.request("/api/status", timeout=5)
                if not tts_status.get("model_ready"):
                    raise RuntimeError("El modelo de Qwen aún no está disponible.")
                self.store.set_state("production_error", "")
                job = self.store.claim(settings)
                if job:
                    self.active_id = job["id"]
                    self.produce(job, settings)
                else:
                    inventory = self.store.inventory()
                    if (inventory.get("on_air", 0) < settings["max_playlist"]
                            and not any(inventory.get(s, 0) for s in ("queued", "waiting", "retry", "running"))
                            and self.store.state("next_refill_check", "") <= now()):
                        self.store.set_state("next_refill_check", after(300))
                        self.requested.set()
            except InterruptedError:
                if job:
                    self.store.release(job["id"])
                break
            except Exception as exc:
                logging.exception("Production failed")
                if job:
                    busy = isinstance(exc, RemoteError) and exc.status == 409
                    status = self.store.retry(job["id"], str(exc), busy=busy)
                    if status == "discarded":
                        self.store.event(f"Noticia descartada automáticamente tras agotar {MAX_RETRIES} reintentos: "
                                         + str(exc)[:500], job["id"])
                    elif status == "retry":
                        self.store.event("Producción aplazada automáticamente: " + str(exc)[:500], job["id"])
                else:
                    self.store.set_state("production_error", str(exc)[:1500])
                    self.stop.wait(15)
            finally:
                self.active_id = None
            self.stop.wait(2)

    def wait_remote(self, client, path, running, timeout):
        deadline = time.monotonic() + timeout
        while not self.stop.is_set():
            value = client.request(path)
            if value["status"] not in running:
                return value
            if time.monotonic() >= deadline:
                raise TimeoutError("Se agotó la espera del servicio; el identificador se conserva para continuar.")
            self.stop.wait(3)
        raise InterruptedError()

    def produce(self, job, settings):
        job_id = job["id"]
        work = job["work"]
        directory = config.DATA / "media" / job_id
        directory.mkdir(exist_ok=True)
        def step(stage):
            self.store.progress(job_id, stage, work)
            if self.stop.is_set():
                raise InterruptedError()

        if "intro_music" not in work:
            work["intro_music"] = intros.select(directory, settings["intro_music_enabled"],
                                                self.store.state("last_intro_name"))
            step(job["stage"])
            if work["intro_music"]:
                self.store.set_state("last_intro_name", work["intro_music"]["name"])
        if "instructions" not in work:
            work.update({"instructions": config.editorial(), "channel_name": settings["channel_name"],
                         "voice_mode": settings["voice_mode"], "voice_name": settings["voice_name"],
                         "tts_language": settings["tts_language"]})
        if not work.get("draft_id"):
            step("extracting")
            material = self.news.request("/api/editorial/prepare", {"article_id": job["article_id"]}, timeout=90)["material"]
            work["material_kind"] = material["kind"]
            work["material_note"] = material["note"]
            work["source_url"] = material["url"]
            if material.get("published_at"):
                published = datetime.fromisoformat(material["published_at"])
                cutoff = datetime.now(timezone.utc) - timedelta(hours=settings["max_age_hours"])
                if published < cutoff or published > datetime.now(timezone.utc) + timedelta(minutes=5):
                    reason = "La fecha del artículo enlazado queda fuera de la ventana de actualidad; se continúa con otra noticia."
                    self.store.skip(job_id, reason)
                    self.store.event(reason, job_id)
                    return
                job["article"]["discovery_published_at"] = job["article"]["published_at"]
                job["article"]["published_at"] = material["published_at"]
                self.store.publication(job_id, job["article"], material["published_at"])
                if not self.store.admits(job, settings):
                    reason = "Con la fecha real del artículo, la política de selección conserva otras noticias de la parrilla."
                    self.store.skip(job_id, reason)
                    self.store.event(reason, job_id)
                    return
            step("drafting")
            draft = self.news.request("/api/editorial/generate", {
                "article_id": job["article_id"], "instructions": work["instructions"],
                "request_key": f"orch:{job_id}:draft:{work.get('draft_generation', 0)}",
            })
            work["draft_id"] = draft["id"]
            step("drafting")
        if not work.get("script"):
            draft = self.wait_remote(self.news, f"/api/editorial/drafts/{work['draft_id']}", {"generating"}, 3600)
            if draft["status"] == "error":
                work.pop("draft_id", None)
                work["draft_generation"] = work.get("draft_generation", 0) + 1
                step("drafting")
                raise RuntimeError(draft["error"])
            result = draft.get("result") or {}
            script = result.get("script", "").strip()
            if not script or len(script) > 5000:
                work.pop("draft_id", None)
                work["draft_generation"] = work.get("draft_generation", 0) + 1
                step("drafting")
                raise RuntimeError("La redacción no tiene texto utilizable por el servicio de voz.")
            work.update({"script": script, "title": result["title"], "notes": result.get("notes", [])})
            step("voicing")
        if not work.get("tts_id"):
            voices = self.tts.request("/api/voices")["voices"]
            if not work.get("voice_id"):
                choice_settings = {**settings, "voice_mode": work.get("voice_mode", settings["voice_mode"])}
                if choice_settings["voice_mode"] == "fixed":
                    choice_settings["voice_name"] = work["voice_name"]
                voice = voice_selection.choose(voices, choice_settings, self.store.state("last_voice_id"))
                work.update({"voice_id": voice["id"], "voice_name": voice["name"]})
                step("voicing")  # Save the random choice before the remote request.
                self.store.set_state("last_voice_id", voice["id"])
            voice = next((voice for voice in voices if voice["id"] == work["voice_id"]), None)
            if not voice:
                raise RuntimeError(f"La voz configurada '{work['voice_name']}' no está importada en Qwen TTS.")
            work["voice_id"] = voice["id"]
            value = self.tts.request("/api/jobs", {"text": work["script"], "voice_id": voice["id"],
                                                  "language": work["tts_language"],
                                                  "request_key": f"orch:{job_id}:tts:{work.get('tts_generation', 0)}"})
            work["tts_id"] = value["id"]
            step("voicing")
        card_article = {**job["article"], "source_url": work.get("source_url") or job["article"].get("linked_url") or job["article"]["url"]}
        visual = visuals.plan(card_article, job_id)
        if not presentation.current(directory, settings, work.get("intro_music"), visual):
            tts = self.wait_remote(self.tts, f"/api/jobs/{work['tts_id']}", {"preparing", "queued", "waiting", "running"}, 10800)
            if tts["status"] != "ready":
                work.pop("tts_id", None)
                work["tts_generation"] = work.get("tts_generation", 0) + 1
                step("voicing")
                raise RuntimeError(tts.get("error") or "Qwen no pudo terminar el audio.")
            step("downloading")
            work["tts_metrics"] = tts["result"]
        step("rendering")
        with self.media_lock:
            info, audio_profile = presentation.prepare(
                directory, card_article, work["title"], work["channel_name"], settings, self.stop,
                lambda target: self.tts.download(f"/api/jobs/{work['tts_id']}/audio.wav", target),
                intro=work.get("intro_music"), visual=visual)
        step("packaging")
        result = {"title": work["title"], "script": work["script"], "notes": work.get("notes", []),
                  "duration_seconds": round(float(info["format"]["duration"]), 2),
                  "presentation": audio_profile,
                  "voice_name": work["voice_name"], "source_url": work.get("source_url") or job["article"].get("linked_url") or job["article"]["url"],
                  "tts": work.get("tts_metrics", {}),
                  "video_url": f"/media/{job_id}/video.mp4", "mp3_url": f"/media/{job_id}/audio.mp3"}
        admitted = self.store.publish(job_id, result, config.load())
        self.store.event("Vídeo terminado e incorporado automáticamente a la parrilla." if admitted else
                         "Vídeo terminado; la política de selección conserva otras noticias de la parrilla.", job_id)
        # The lossless input is disposable once the finished video and MP3 exist.
        (directory / "audio.wav").unlink(missing_ok=True)

    def presentations(self):
        """Update only finished on-air clips; never run Ollama or enqueue TTS."""
        while not self.stop.is_set():
            failed = False
            try:
                settings = config.load()
                for job in self.store.playlist():
                    if self.stop.is_set():
                        return
                    directory = config.DATA / "media" / job["id"]
                    intro = job["work"].get("intro_music")
                    try:
                        with self.media_lock:
                            current_job = self.store.get(job["id"])
                            if not current_job or not current_job["active"]:
                                continue
                            card_article = {**job["article"], "source_url": job["result"].get("source_url") or job["article"].get("linked_url") or job["article"]["url"]}
                            visual = visuals.plan(card_article, job["id"])
                            wanted = presentation.profile(settings, intro, visual)
                            if presentation.current(directory, settings, intro, visual) and job["result"].get("presentation") == wanted:
                                continue
                            self.presentation_active_id = job["id"]
                            tts_id = job["work"].get("tts_id")
                            info, audio_profile = presentation.prepare(
                                directory, card_article, job["result"]["title"],
                                job["work"].get("channel_name", settings["channel_name"]), settings, self.stop,
                                lambda target: self.tts.download(f"/api/jobs/{tts_id}/audio.wav", target), intro=intro, visual=visual)
                        result = {**job["result"], "duration_seconds": round(float(info["format"]["duration"]), 2),
                                  "presentation": audio_profile}
                        self.store.update_presentation(job["id"], result)
                        self.store.event("Presentación de la noticia actualizada usando el audio guardado.", job["id"])
                    except InterruptedError:
                        return
                    except Exception as exc:
                        failed = True
                        logging.exception("Presentation update failed")
                        self.store.set_state("presentation_error", str(exc)[:1500])
                    finally:
                        self.presentation_active_id = None
                if not failed:
                    self.store.set_state("presentation_error", "")
            except Exception as exc:
                logging.exception("Presentation maintenance failed")
                self.store.set_state("presentation_error", str(exc)[:1500])
            self.stop.wait(30)

    def cleanup(self):
        retention.run(self.store, self.tts, self.media_lock, self.stop)

    def status(self):
        settings = config.load()
        try:
            broadcast = json.loads((config.DATA / "broadcast.json").read_text())
        except (ValueError, OSError):
            broadcast = {}
        return {"settings": settings, "scanning": self.scanning, "active_id": self.active_id,
                "presentation_active_id": self.presentation_active_id,
                "presentation_error": self.store.state("presentation_error", ""),
                "cleanup_error": self.store.state("cleanup_error", ""),
                "last_cleanup_at": self.store.state("last_cleanup_at"),
                "inventory": self.store.inventory(), "source_warnings": self.store.state("source_warnings", []),
                "source_balance": self.store.source_balance(settings),
                "playlist": self.store.playlist(), "jobs": self.store.jobs(), "events": self.store.events(),
                "last_scan_at": self.store.state("last_scan_at"), "next_scan_at": self.store.state("next_scan_at"),
                "scan_count": self.store.state("last_scan_count", {}), "scan_error": self.store.state("scan_error", ""),
                "production_error": self.store.state("production_error", ""), "broadcast": broadcast,
                "youtube": youtube_control.public_status(),
                "stream_url": "/live/index.m3u8", "automatic": True, "output": "local", "max_retries": MAX_RETRIES}
