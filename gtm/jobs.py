"""Rows of the `jobs` table: enqueue, claim, finish. The worker runs them."""
from datetime import datetime, timedelta, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(db, kind: str, payload: dict | None = None, run_after: datetime | None = None) -> str:
    row = {"kind": kind, "payload": payload or {}}
    if run_after:
        row["run_after"] = run_after.isoformat()
    return db.table("jobs").insert(row).execute().data[0]["id"]


def claim(db) -> dict | None:
    """Atomically take the oldest due queued job (marked running), or None."""
    data = db.rpc("claim_job").execute().data
    row = data[0] if isinstance(data, list) and data else data
    return row if row and row.get("id") else None  # an empty queue comes back as a row of nulls


def finish(db, job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
    db.table("jobs").update({"status": status, "result": result, "error": error, "finished_at": _now().isoformat()}).eq("id", job_id).execute()


def requeue_stale(db, older_than_minutes: int = 60) -> int:
    cutoff = (_now() - timedelta(minutes=older_than_minutes)).isoformat()
    return len(db.table("jobs").update({"status": "queued", "started_at": None}).eq("status", "running").lt("started_at", cutoff).execute().data)
