"""Publication budget and production cadence, independent of source selection."""

from datetime import datetime, timedelta, timezone


def plan(limit, publications, last_started_at=None, current=None):
    """Count real admissions in a rolling hour; pace starts between successes.

    Timing the next start from the previous successful job's start allows slow
    synthesis to use the interval. Timing from its completion would add an
    unnecessary full interval after every narration. Failures reserve no quota.
    """
    current = current or datetime.now(timezone.utc)
    interval = 3600 / limit
    cutoff = current - timedelta(hours=1)
    timestamps = sorted(datetime.fromisoformat(value) for value in publications)
    recent = [value for value in timestamps if cutoff < value <= current]
    deadlines = []
    if last_started_at:
        deadlines.append(datetime.fromisoformat(last_started_at) + timedelta(seconds=interval))
    if len(recent) >= limit:
        # If the limit was lowered, enough existing publications must expire.
        deadlines.append(recent[len(recent) - limit] + timedelta(hours=1))
    next_start = max(deadlines, default=current)
    wait = max(0, (next_start - current).total_seconds())
    return {"target_per_hour": limit, "published_last_hour": len(recent),
            "remaining": max(0, limit - len(recent)), "interval_seconds": interval,
            "can_start": wait <= 0, "wait_seconds": round(wait, 1),
            "next_start_at": next_start.isoformat() if wait > 0 else None,
            "reason": "hourly_limit" if len(recent) >= limit else "cadence" if wait > 0 else "available"}
