import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gtm.db import fetch_all

METROS = Path(__file__).parent / "data" / "metros.csv"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_metros(path: Path = METROS) -> list[dict]:
    with open(path, newline="") as f:
        return [{**r, "metro_rank": int(r["metro_rank"])} for r in csv.DictReader(f)]


def seed_coverage(db, rows: list[dict]) -> int:
    have = {(r["metro"], r["state"], r["tile"]) for r in fetch_all(lambda: db.table("coverage").select("metro,state,tile").order("id"))}
    new = [{**r, "seq": i} for i, r in enumerate(rows) if (r["metro"], r["state"], r["tile"]) not in have]
    for i in range(0, len(new), 500):
        db.table("coverage").insert(new[i:i + 500]).execute()
    return len(new)


def claim_tiles(db, n: int) -> list[dict]:
    """Flip up to n pending tiles (lowest seq first) to running. A lost race (row no longer pending) is skipped.
    ponytail: per-row conditional update, fine for one or two workers."""
    got = []
    for c in db.table("coverage").select("id").eq("status", "pending").order("seq").limit(n).execute().data:
        r = db.table("coverage").update({"status": "running", "started_at": _now()}).eq("id", c["id"]).eq("status", "pending").execute().data
        got += r
    return got


def release_tile(db, tile_id: str) -> None:
    db.table("coverage").update({"status": "pending"}).eq("id", tile_id).execute()


def reset_stale(db, hours: int = 2) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return len(db.table("coverage").update({"status": "pending"}).eq("status", "running").lt("started_at", cutoff).execute().data)
