"""Daily schedule: the worker loop calls `tick`, which enqueues at most one walk job per UTC day; `queue_tick` the same for the morning sheet queue."""
from datetime import datetime, timezone

from gtm.jobs import enqueue
from gtm.settings_store import setting


def tick(db, now: datetime | None = None, kind: str = "walk") -> str | None:
    now = now or datetime.now(timezone.utc)
    if not setting("walk_schedule_enabled", db) or now.hour < setting("walk_hour_utc", db):
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # any status counts: a failed walk today must not retry-storm
    if db.table("jobs").select("id").eq("kind", kind).gte("created_at", midnight).limit(1).execute().data:
        return None
    return enqueue(db, kind, {"argv": ["--tiles", str(setting("walk_tiles_per_run", db))]})


def queue_tick(db, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    if not setting("sheet_queue_on", db) or now.hour < setting("sheet_queue_hour_utc", db):
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # any status counts: a failed run today must not retry-storm
    if db.table("jobs").select("id").eq("kind", "sheet-queue").gte("created_at", midnight).limit(1).execute().data:
        return None
    return enqueue(db, "sheet-queue", {"argv": ["--confirm"]})


def paint_tick(db, now: datetime | None = None) -> str | None:
    """One sheet-paint per UTC day, an hour after the queue hour so it paints what the queue just wrote."""
    now = now or datetime.now(timezone.utc)
    if not (setting("sheet_writeback_on", db) and setting("sheet_id", db)) or now.hour < min(setting("sheet_queue_hour_utc", db) + 1, 23):
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # any status counts: a failed run today must not retry-storm
    if db.table("jobs").select("id").eq("kind", "sheet-paint").gte("created_at", midnight).limit(1).execute().data:
        return None
    return enqueue(db, "sheet-paint", {"argv": ["--confirm"]})
