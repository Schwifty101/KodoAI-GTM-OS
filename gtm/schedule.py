"""Daily schedule: the worker loop calls `tick`, which enqueues at most one walk job per UTC day."""
from datetime import datetime, timezone

from gtm.jobs import enqueue
from gtm.settings_store import setting


def tick(db, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    if not setting("walk_schedule_enabled", db) or now.hour < setting("walk_hour_utc", db):
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # any status counts: a failed walk today must not retry-storm
    if db.table("jobs").select("id").eq("kind", "walk").gte("created_at", midnight).limit(1).execute().data:
        return None
    return enqueue(db, "walk", {"argv": ["--tiles", str(setting("walk_tiles_per_run", db))]})
