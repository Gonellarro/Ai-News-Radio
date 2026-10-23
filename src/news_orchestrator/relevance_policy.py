"""Optional editorial ranking. Pure functions; no model, files or database."""

import hashlib
import json
import math
from datetime import datetime, timezone

DIMENSIONS = {"relevance": "Afinidad con el canal", "impact": "Impacto", "novelty": "Novedad", "substance": "Contenido informativo"}
DEFAULT_CRITERIA = """Prioriza información concreta y útil sobre inteligencia artificial: lanzamientos disponibles,
investigación con aportaciones claras, herramientas, aplicaciones y cambios que afecten a sus usuarios.
Valora la novedad del hecho descrito y su alcance. Penaliza publicidad, descuentos, titulares vacíos,
repeticiones sin aportación y especulación presentada como hecho. Una opinión puede ser útil si aporta
análisis sustancial. No equipares popularidad, nombre de una empresa o fuente oficial con relevancia.
Puntúa únicamente lo que permiten inferir el titular y el extracto; señala cuando falta información.
No verifiques hechos ni certifiques credibilidad: no tienes acceso al artículo completo ni a otras fuentes."""
DEFAULTS = {"mode": "off", "max_evaluations_per_hour": 20, "interval_seconds": 3600,
            "influence": 0.6, "weights": {"relevance": 0.4, "impact": 0.25, "novelty": 0.2, "substance": 0.15},
            "criteria": DEFAULT_CRITERIA}


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("relevance contiene opciones desconocidas.")
    result = {**DEFAULTS, **value}
    if result["mode"] not in ("off", "observe", "rank"):
        raise ValueError("relevance.mode debe ser off, observe o rank.")
    for key, low, high in (("max_evaluations_per_hour", 1, 100), ("interval_seconds", 3600, 86400)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"relevance.{key} debe estar entre {low} y {high}.")
    if type(result["influence"]) not in (int, float) or not math.isfinite(result["influence"]) or not 0 <= result["influence"] <= 1:
        raise ValueError("relevance.influence debe estar entre 0 y 1.")
    weights = result["weights"]
    if (not isinstance(weights, dict) or set(weights) != set(DIMENSIONS) or any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100 for v in weights.values()
    ) or sum(weights.values()) <= 0):
        raise ValueError("relevance.weights debe asignar pesos positivos o cero a relevance, impact, novelty y substance; al menos uno debe ser positivo.")
    if not isinstance(result["criteria"], str) or not 1 <= len(result["criteria"].strip()) <= 6000:
        raise ValueError("relevance.criteria debe tener entre 1 y 6.000 caracteres.")
    return result


def evidence(job):
    article = job["article"]
    return {"id": job["article_id"], "title": str(article.get("title", ""))[:500],
            "summary": str(article.get("summary") or article.get("content") or "")[:900],
            "source": str(article.get("source_name", ""))[:150],
            "published_at": job["published_at"]}


def fingerprint(job, settings):
    # Modes, budgets and influence do not alter an editorial judgement.
    payload = {"version": 2, "topic": settings["topic"], "criteria": settings["relevance"]["criteria"],
               "evidence": evidence(job)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def current(job, settings):
    value = job.get("relevance") or {}
    return value if value.get("fingerprint") == fingerprint(job, settings) else {}


def score(job, settings):
    value = current(job, settings)
    if value.get("status") != "ready":
        return None
    return weighted_score(value, settings)


def weighted_score(value, settings):
    weights = settings["relevance"]["weights"]
    return round(sum(value["scores"][k] * w for k, w in weights.items()) / sum(weights.values()), 1)


def last_success(value):
    """Keep a single previous judgement for display, never for selection."""
    if value.get("status") == "ready" and value.get("scores"):
        return {key: item for key, item in value.items() if key != "previous"}
    return value.get("previous") or {}


def criteria_key(settings):
    return hashlib.sha256(json.dumps({"topic": settings["topic"],
        "criteria": settings["relevance"]["criteria"]}, sort_keys=True).encode()).hexdigest()


def order(job, settings):
    recent = datetime.fromisoformat(job["published_at"]).timestamp()
    value = score(job, settings) if settings.get("relevance", {}).get("mode") == "rank" else None
    if value is None:
        # Neutral estimate for unrated candidates: they can still reach production.
        value = 50
    if settings.get("relevance", {}).get("mode") != "rank":
        return (-recent, job["id"])
    age = max(0, datetime.now(timezone.utc).timestamp() - recent) / 3600
    freshness = 100 * max(0, 1 - age / settings["max_age_hours"])
    influence = settings["relevance"]["influence"]
    return (-(influence * value + (1-influence) * freshness), -recent, job["id"])
