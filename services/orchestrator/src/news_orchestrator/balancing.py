"""Replaceable, pure selection policies. No database, network or media work."""

from collections import Counter, defaultdict
from datetime import datetime
import math
from urllib.parse import urlsplit
from news_orchestrator import playlist_rotation, relevance_policy


def source(job):
    article = job["article"]
    host = urlsplit(article.get("url", "")).hostname or "unknown"
    return {"id": article.get("source_id") or "domain:" + host,
            "name": article.get("source_name") or host,
            "platform": article.get("platform") or "web"}


def resumable(job):
    work = job.get("work") or {}
    return any(work.get(key) for key in ("tts_id", "script", "draft_id"))


def _recent(job):
    return (-datetime.fromisoformat(job["published_at"]).timestamp(), job["id"])


def _order(job, options):
    orders = options.setdefault("orders", {})
    if job["id"] in orders:
        return orders[job["id"]]
    settings = options.get("editorial_settings")
    orders[job["id"]] = relevance_policy.order(job, settings) if settings else _recent(job)
    return orders[job["id"]]


def _options(settings):
    return {**settings["balancing"], "editorial_settings": settings}


class LatestPolicy:
    description = "Primero las noticias más recientes"

    def queue(self, candidates, published, running, active, limit, options):
        return sorted(candidates, key=lambda job: (not resumable(job), *_order(job, options)))[:limit]


class FairPolicy:
    description = "Equilibrio por publicaciones acumuladas de cada fuente"

    @staticmethod
    def weight(source_id, options):
        return options["weights"].get(source_id, 1.0)

    def queue(self, candidates, published, running, active, limit, options):
        projected = Counter(published)
        projected.update(source(job)["id"] for job in running)
        on_air = Counter(source(job)["id"] for job in active)
        groups = defaultdict(list)
        for job in sorted(candidates, key=lambda job: (not resumable(job), *_order(job, options))):
            groups[source(job)["id"]].append(job)
        selected = []
        while groups and len(selected) < limit:
            def priority(source_id):
                head = groups[source_id][0]
                weight = self.weight(source_id, options)
                return (not resumable(head), projected[source_id] / weight,
                        on_air[source_id] / weight, *_order(head, options), source_id)
            chosen = min(groups, key=priority)
            selected.append(groups[chosen].pop(0))
            projected[chosen] += 1  # Reserve this slot before choosing the next.
            if not groups[chosen]:
                del groups[chosen]
        return selected


POLICIES = {"fair": FairPolicy(), "latest": LatestPolicy()}


def validate(value):
    if not isinstance(value, dict) or not isinstance(value.get("strategy"), str) or value["strategy"] not in POLICIES:
        raise ValueError("balancing.strategy debe ser fair o latest.")
    weights = value.setdefault("weights", {})
    if not isinstance(weights, dict) or any(
        not isinstance(key, str) or not key.strip() or type(weight) not in {int, float}
        or not math.isfinite(weight) or not 0.01 <= weight <= 100
        for key, weight in weights.items()
    ):
        raise ValueError("balancing.weights debe asignar pesos de 0,01 a 100 a identificadores de fuente.")
    return value


def policy(settings):
    return POLICIES[settings["balancing"]["strategy"]]


def select(candidates, published, running, active, limit, settings):
    # Source quotas and editorial scores choose production work. They do not
    # protect old clips from replacement by completed newcomers.
    options = _options(settings)
    eligible = [job for job in candidates if not job.get("manual_excluded") and
                (resumable(job) or playlist_rotation.admits(job, active, settings["max_playlist"]))]
    requested = sorted((job for job in eligible if job.get("requested")), key=_recent)[:limit]
    ids = {job["id"] for job in requested}
    return requested + policy(settings).queue([job for job in eligible if job["id"] not in ids], published,
                                             running + requested, active, limit-len(requested), options)
