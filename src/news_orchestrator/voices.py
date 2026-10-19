"""Choose once per story; keep the chosen voice through chunks and retries."""

import secrets


def choose(voices, settings, previous=None):
    voices = [v for v in voices if v.get("enabled", True)]
    if settings["voice_mode"] == "fixed":
        voice_id = settings.get("qwen_voice_id", "")
        choices = [v for v in voices if v["id"] == voice_id] if voice_id else [
            v for v in voices if v["name"].casefold() == settings["voice_name"].casefold()]
        # Removing/disabling the fixed voice must not strand automatic news.
        if not choices:
            return choose(voices, {**settings, "voice_mode": "random"}, previous)
    else:
        allowed = {v.casefold() for v in settings["voice_names"]}
        excluded = {v.casefold() for v in settings["voice_exclude"]}
        choices = [v for v in voices if v["name"].casefold() not in excluded
                   and (not allowed or v["name"].casefold() in allowed)]
        alternatives = [v for v in choices if v["id"] != previous]
        choices = alternatives or choices
    if not choices:
        raise RuntimeError("No hay voces activas que coincidan con la selección del canal. Añade o activa una voz en la biblioteca de Qwen.")
    return secrets.choice(choices)
