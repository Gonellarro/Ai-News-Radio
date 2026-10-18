"""Read every local candidate page without letting one platform crowd out others."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode


def candidates(client, settings, stop):
    sources = settings["source_ids"] or [""]
    platforms = ["web", "reddit", "mastodon", "bluesky"] if settings["platform"] == "all" else [settings["platform"]]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings["max_age_hours"])
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    found = {}
    for platform in platforms:
        for source_id in sources:
            for offset in range(0, 10000, 100):
                if stop.is_set():
                    raise InterruptedError()
                params = {"q": settings.get("query", ""), "time_range": "day" if settings["max_age_hours"] <= 24 else "week",
                          "language": settings["language"], "platform": platform, "source_id": source_id,
                          "offset": offset, "limit": 100}
                result = client.request("/api/news?" + urlencode(params))
                for article in result["results"]:
                    if not article.get("id") or not article.get("published_at"):
                        continue
                    try:
                        published = datetime.fromisoformat(article["published_at"])
                    except ValueError:
                        continue
                    if published.tzinfo is not None and cutoff <= published <= future:
                        found[article["id"]] = article
                if offset + len(result["results"]) >= result.get("total_count", 0) or len(result["results"]) < 100:
                    break
    return sorted(found.values(), key=lambda a: a["published_at"], reverse=True)
