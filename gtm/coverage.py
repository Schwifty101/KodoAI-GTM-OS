import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gtm import budget
from gtm.apify import MIN_CAP
from gtm.clean import run_clean
from gtm.db import fetch_all
from gtm.scrape import new_batch, scrape_city
from gtm.settings_store import setting

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


def run_walk(db, run_actor, tiles: int, queries: list[str] | None = None, max_places: int | None = None, escalate_at: float | None = None) -> dict:
    """Scrape and clean the next uncovered tiles. A query is followed by the next one only while it filled its cap
    (items returned >= escalate_at * max_places, counted before dedupe); the last query also filling it flags the tile saturated."""
    queries = queries or [q.strip() for q in setting("walk_queries").split(",") if q.strip()]
    max_places = max_places or setting("walk_max_places")
    escalate_at = setting("walk_escalate_at") if escalate_at is None else escalate_at
    out = {"tiles": 0, "queries": 0, "new": 0, "known": 0, "saturated": 0}
    reset_stale(db)
    for _ in range(tiles):
        got = claim_tiles(db, 1)  # one at a time: a raise never strands later tiles as running
        if not got:
            break
        t = got[0]
        batch, n, found, new, known, ran = None, 0, 0, 0, 0, 0
        try:
            budget.require("apify", MIN_CAP)  # before new_batch: a blocked tile leaves no empty batch
            batch = new_batch(db, t["tile"], t["state"], [queries[0]])

            def counted(inp):
                nonlocal n
                items, usd = run_actor(inp)
                n = len(items)
                return items, usd

            full = True
            for q in queries:
                if ran:
                    budget.require("apify", MIN_CAP)
                a, b = scrape_city(db, counted, t["tile"], t["state"], [q], batch, max_places)
                ran, found, new, known = ran + 1, found + n, new + a, known + b
                full = n >= escalate_at * max_places
                if not full:
                    break
            db.table("batches").update({"query": ", ".join(queries[:ran])}).eq("id", batch).execute()
            run_clean(db, batch)
            db.table("coverage").update({"status": "done", "places_found": found, "new_leads": new, "saturated": full, "queries_run": ran,
                                         "scrape_batch_id": batch, "scraped_at": _now()}).eq("id", t["id"]).execute()
        except budget.BudgetExceeded:
            if ran:
                run_clean(db, batch)  # leads from the queries that ran must not stay `scraped`
            release_tile(db, t["id"])
            raise
        except Exception as e:
            if ran:
                run_clean(db, batch)
            db.table("coverage").update({"status": "failed", "error": str(e)[:500]}).eq("id", t["id"]).execute()
            continue
        out["tiles"] += 1
        out["queries"] += ran
        out["new"] += new
        out["known"] += known
        out["saturated"] += full
    return out
