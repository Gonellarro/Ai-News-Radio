"""Calendar slots in local wall time, persisted separately from job selection."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INTERVALS = {43200: "Cada 12 horas · 00:00 y 12:00", 21600: "Cada 6 horas · 00:00, 06:00, 12:00 y 18:00",
             3600: "Cada hora en punto", 1800: "Cada media hora · en punto y a y media"}
DEFAULT_ZONE = "Europe/Madrid"


def validate(interval, zone):
    if type(interval) is not int or interval not in INTERVALS:
        raise ValueError("scan_interval_seconds debe ser 43200 (12 h), 21600 (6 h), 3600 (1 h) o 1800 (media hora).")
    if not isinstance(zone, str) or not 1 <= len(zone) <= 100:
        raise ValueError("schedule_timezone debe ser una zona horaria válida, por ejemplo Europe/Madrid.")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("schedule_timezone no es una zona horaria disponible.") from exc


def next_slot(interval, zone=DEFAULT_ZONE, current=None):
    """Next strictly future slot; skip nonexistent times and include both folds."""
    validate(interval, zone)
    current = current or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("El instante de referencia debe incluir zona horaria.")
    current = current.astimezone(timezone.utc)
    local_zone = ZoneInfo(zone)
    today = current.astimezone(local_zone).date()
    candidates = set()
    for day in (today, today + timedelta(days=1)):
        midnight = datetime.combine(day, time())
        for seconds in range(0, 86400, interval):
            wall = midnight + timedelta(seconds=seconds)
            for fold in (0, 1):
                value = wall.replace(tzinfo=local_zone, fold=fold).astimezone(timezone.utc)
                # A spring-forward gap must not manufacture a late/duplicate slot.
                if value.astimezone(local_zone).replace(tzinfo=None) == wall and value > current:
                    candidates.add(value)
    return min(candidates)


def signature(settings):
    return {"interval": settings["scan_interval_seconds"], "timezone": settings["schedule_timezone"]}


def synchronize(store, settings, *, reset=False, current=None):
    """Re-arm after restart/config edits; never replay all missed slots."""
    spec = signature(settings)
    if reset or store.state("scan_calendar") != spec or not store.state("next_scan_at"):
        store.set_state("scan_calendar", spec)
        store.set_state("next_scan_at", next_slot(spec["interval"], spec["timezone"], current).isoformat())
    return store.state("next_scan_at")


def advance(store, settings, current=None):
    store.set_state("scan_calendar", signature(settings))
    store.set_state("next_scan_at", next_slot(settings["scan_interval_seconds"], settings["schedule_timezone"], current).isoformat())


def public(settings):
    return {"timezone": settings["schedule_timezone"], "interval_seconds": settings["scan_interval_seconds"],
            "description": INTERVALS[settings["scan_interval_seconds"]],
            "options": [{"seconds": value, "label": label} for value, label in INTERVALS.items()]}
