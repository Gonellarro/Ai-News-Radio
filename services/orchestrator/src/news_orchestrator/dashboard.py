"""Dashboard API facade. Other services keep ownership of their own data."""

import re

from news_orchestrator import config, playlist_control


class Dashboard:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.playlist = playlist_control.Playlist(pipeline)

    def get(self, name, params):
        if name == "relevance":
            return self.pipeline.relevance.info(params)
        if name == "config":
            return config.snapshot()
        if name == "playlist":
            return self.playlist.get()
        if name == "library":
            return playlist_control.library(self.pipeline.store, params)
        if name == "sources":
            return {**self.pipeline.news.request("/api/sources/config", timeout=8),
                    "status": self.pipeline.news.request("/api/sources", timeout=8)}
        if name == "editorial":
            text = config.editorial()
            return {"text": text, "revision": config.revision(text)}
        raise ValueError("Panel no encontrado.")

    def post(self, name, payload):
        if name == "relevance/evaluate":
            return self.pipeline.relevance.request_manual()
        if name == "config":
            # Serialize changes to capacity with manual playlist edits.
            with self.pipeline.media_lock:
                result = config.update(payload, self.pipeline.store)
            self.pipeline.store.event("Configuración del canal actualizada desde el panel de control.")
            if {"relevance", "topic"} & set(payload["changes"]):
                self.pipeline.relevance.requested.set()
            return result
        if name == "playlist":
            return self.playlist.save(payload)
        if name == "request":
            return self.playlist.request(payload.get("id"))
        if name == "sources":
            result = self.pipeline.news.request("/api/sources/config", payload, timeout=15)
            ids = {source["id"] for source in result["catalog"]["sources"]}
            with config.WRITE_LOCK:
                value = config.load()
                allowed = [source_id for source_id in value["source_ids"] if source_id in ids]
                if allowed != value["source_ids"]:
                    value["source_ids"] = allowed
                    config.atomic_json(config.CONFIG / "channel.json", value)
            self.pipeline.store.event("Catálogo de fuentes actualizado; se respetan los intervalos de consulta.")
            return result
        if name == "editorial":
            text = payload.get("text")
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 6000:
                raise ValueError("El estilo editorial debe contener entre 1 y 6.000 caracteres.")
            with config.WRITE_LOCK:
                if payload.get("revision") != config.revision(config.editorial()):
                    raise playlist_control.Conflict("El estilo editorial ha cambiado. Recarga antes de guardar.")
                target = config.CONFIG / "editorial.md"
                temporary = target.with_suffix(".tmp")
                temporary.write_text(text.strip() + "\n")
                temporary.replace(target)
            self.pipeline.store.event("Estilo editorial actualizado para los trabajos nuevos.")
            return self.get("editorial", {})
        if name in {"voices/add", "voices/import"} or re.fullmatch(r"voices/[a-f0-9]{32}/(update|delete)", name):
            remote = "/api/voices" if name == "voices/add" else "/api/" + name
            return self.pipeline.tts.request(remote, payload, timeout=60)
        raise ValueError("Acción de panel no encontrada.")
