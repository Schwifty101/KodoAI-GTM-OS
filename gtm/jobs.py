"""Rows of the `jobs` table: enqueue, claim, finish. The worker runs them."""
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db, kind: str, payload: dict | None = None, run_after: datetime | None = None) -> str:
    row = {"kind": kind, "payload": payload or {}}
    if run_after:
        row["run_after"] = run_after.isoformat()
    return db.table("jobs").insert(row).execute().data[0]["id"]


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
