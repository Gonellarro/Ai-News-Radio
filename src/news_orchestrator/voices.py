"""Choose once per story; keep the chosen voice through chunks and retries."""

import secrets


def choose(voices, settings, previous=None):
    if settings["voice_mode"] == "fixed":
        choices = [v for v in voices if v["name"].casefold() == settings["voice_name"].casefold()]
    else:
        allowed = {v.casefold() for v in settings["voice_names"]}
        excluded = {v.casefold() for v in settings["voice_exclude"]}
        choices = [v for v in voices if v["name"].casefold() not in excluded
                   and (not allowed or v["name"].casefold() in allowed)]
        alternatives = [v for v in choices if v["id"] != previous]
        choices = alternatives or choices
    if not choices:
        raise RuntimeError("No hay voces importadas que coincidan con la selección del canal.")
    return secrets.choice(choices)
