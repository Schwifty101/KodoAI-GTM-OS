"""Rows of the `jobs` table: enqueue, claim, finish. The worker runs them."""
from datetime import datetime, timedelta, timezone

from postgrest.exceptions import APIError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db, kind: str, payload: dict | None = None, run_after: datetime | None = None) -> str:
    """Queue a job and return its id. A queued or running job with the same kind and argv makes the database refuse the insert (unique index jobs_open_unique,
    migration 0016; another tab or the autopilot won the race): that open job's id comes back instead, which is what every caller wanted anyway."""
    row = {"kind": kind, "payload": payload or {}}
    if run_after:
        row["run_after"] = run_after.isoformat()
    try:
        return db.table("jobs").insert(row).execute().data[0]["id"]
    except APIError as e:
        twin = _open_twin(db, kind, row["payload"].get("argv")) if e.code == "23505" else None
        if not twin:
            raise  # not a duplicate, or the twin finished in the meantime: the next tick tries again
        return twin


def _open_twin(db, kind: str, argv) -> str | None:
    rows = db.table("jobs").select("id,payload").eq("kind", kind).in_("status", ["queued", "running"]).execute().data
    return next((r["id"] for r in rows if (r["payload"] or {}).get("argv") == argv), None)


def claim(db, include_test: bool = False) -> dict | None:
    """Atomically take the oldest due queued job (marked running), or None."""
    rpc = db.rpc("claim_job", {"include_test": True}) if include_test else db.rpc("claim_job")
    data = rpc.execute().data
    row = data[0] if isinstance(data, list) and data else data
    return row if row and row.get("id") else None  # an empty queue comes back as a row of nulls


def finish(db, job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
    db.table("jobs").update({"status": status, "result": result, "error": error, "finished_at": _now().isoformat()}).eq("id", job_id).eq("status", "running").execute()


def heartbeat(db, job_id: str) -> None:
    try:
        db.table("jobs").update({"heartbeat_at": _now().isoformat()}).eq("id", job_id).eq("status", "running").execute()
    except Exception:
        pass  # a blip must not kill the job; a long outage lets requeue_stale take it


def requeue_stale(db, older_than_minutes: int = 5) -> int:
    cutoff = (_now() - timedelta(minutes=older_than_minutes)).isoformat()
    stale = f"heartbeat_at.lt.{cutoff},and(heartbeat_at.is.null,started_at.lt.{cutoff})"
    db.table("jobs").update({"status": "failed", "error": "stale after 3 attempts", "finished_at": _now().isoformat()}).eq("status", "running").or_(stale).gte("attempts", 3).execute()
    return len(db.table("jobs").update({"status": "queued", "started_at": None, "heartbeat_at": None}).eq("status", "running").or_(stale).lt("attempts", 3).execute().data)
