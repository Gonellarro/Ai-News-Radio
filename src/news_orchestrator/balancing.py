"""Replaceable, pure selection policies. No database, network or media work."""

from collections import Counter, defaultdict
from datetime import datetime
import math
from urllib.parse import urlsplit


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


class LatestPolicy:
    description = "Primero las noticias más recientes"

    def queue(self, candidates, published, running, active, limit, options):
        return sorted(candidates, key=lambda job: (not resumable(job), *_recent(job)))[:limit]

    def playlist(self, jobs, published, limit, options):
        return sorted(jobs, key=_recent)[:limit]


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
        for job in sorted(candidates, key=lambda job: (not resumable(job), *_recent(job))):
            groups[source(job)["id"]].append(job)
        selected = []
        while groups and len(selected) < limit:
            def priority(source_id):
                head = groups[source_id][0]
                weight = self.weight(source_id, options)
                return (not resumable(head), projected[source_id] / weight,
                        on_air[source_id] / weight, *_recent(head), source_id)
            chosen = min(groups, key=priority)
            selected.append(groups[chosen].pop(0))
            projected[chosen] += 1  # Reserve this slot before choosing the next.
            if not groups[chosen]:
                del groups[chosen]
        return selected

    def playlist(self, jobs, published, limit, options):
        groups = defaultdict(list)
        for job in sorted(jobs, key=_recent):
            groups[source(job)["id"]].append(job)
        kept, allocated = [], Counter()
        while groups and len(kept) < limit:
            def priority(source_id):
                weight = self.weight(source_id, options)
                return ((allocated[source_id] + 1) / weight,
                        published.get(source_id, 0) / weight,
                        *_recent(groups[source_id][0]), source_id)
            chosen = min(groups, key=priority)
            kept.append(groups[chosen].pop(0))
            allocated[chosen] += 1
            if not groups[chosen]:
                del groups[chosen]
        return kept


POLICIES = {"fair": FairPolicy(), "latest": LatestPolicy()}


def validate(value):
    if not isinstance(value, dict) or value.get("strategy") not in POLICIES:
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


def keep(jobs, published, settings):
    return policy(settings).playlist(jobs, published, settings["max_playlist"], settings["balancing"])


def admits(job, active, published, settings):
    if len(active) < settings["max_playlist"]:
        return True
    # Predict the same counters and playlist that an actual publication would
    # produce. An older, underrepresented source can displace a crowded source.
    projected = dict(published)
    source_id = source(job)["id"]
    projected[source_id] = projected.get(source_id, 0) + 1
    return any(item["id"] == job["id"] for item in keep(active + [job], projected, settings))


def select(candidates, published, running, active, limit, settings):
    eligible = [job for job in candidates if resumable(job) or admits(job, active, published, settings)]
    return policy(settings).queue(eligible, published, running, active, limit, settings["balancing"])
