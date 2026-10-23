"""Playlist lifetime policy, independent of candidate ranking and source quotas."""

from datetime import datetime


def entered(job):
    """Compare time on air, never the article date or its editorial score."""
    value = job.get("playlist_entered_at") or job["updated_at"]
    return (datetime.fromisoformat(value).timestamp(), job["id"])


def admits(job, active, limit):
    if job.get("manual_excluded"):
        return False
    if any(item["id"] == job["id"] for item in active):
        return True
    # Every completed newcomer can replace an unpinned clip, regardless of
    # which sources or scores are currently represented in the playlist.
    return sum(bool(item.get("pinned")) for item in active) < limit


def keep(jobs, limit):
    """Keep pinned clips and the newest admissions; retire the oldest first."""
    available = [job for job in jobs if not job.get("manual_excluded")]
    protected = sorted((job for job in available if job.get("pinned")), key=entered, reverse=True)
    rotating = sorted((job for job in available if not job.get("pinned")), key=entered, reverse=True)
    return (protected + rotating[:max(0, limit-len(protected))])[:limit]
