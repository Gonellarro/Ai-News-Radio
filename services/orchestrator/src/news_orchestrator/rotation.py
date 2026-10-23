"""Pure production allowance for a calendar-triggered update batch."""

from datetime import datetime, timezone


def plan(cycle, published, published_last_hour, next_scan_at, current=None, default_quota=0):
    current = current or datetime.now(timezone.utc)
    limit = cycle["quota"] if cycle else default_quota
    remaining = max(0, limit-published)
    retry = datetime.fromisoformat(cycle["retry_at"]) if cycle and cycle.get("retry_at") else None
    retry_wait = bool(retry and retry > current)
    can_start = bool(cycle and cycle["status"] in {"ready", "producing"} and remaining and not retry_wait)
    deadline = datetime.fromisoformat(next_scan_at) if next_scan_at else None
    if retry_wait and cycle["status"] in {"ready", "producing"}:
        deadline = retry
    reason = ("available" if can_start else "retry" if retry_wait else "collecting" if cycle and cycle["status"] == "collecting"
              else "cycle_limit" if cycle and published >= limit else "scheduled_update")
    return {"target_per_update": limit, "published_this_cycle": published, "remaining": remaining,
            "published_last_hour": published_last_hour, "cycle_id": cycle["id"] if cycle else None,
            "cycle_status": cycle["status"] if cycle else "waiting", "reason": reason,
            "can_start": can_start, "wait_seconds": 0 if can_start else max(1, (deadline-current).total_seconds()) if deadline else 10,
            "next_start_at": None if can_start else deadline.isoformat() if deadline else None}
