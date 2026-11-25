import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gtm import budget
from gtm.apify import MIN_CAP
from gtm.clean import run_clean
from gtm.db import fetch_all
from gtm.serper_maps import PLACES_PER_CALL, QUERIES
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


SUCCESS = {"enriched", "signalled", "selected", "drafted", "sent", "replied", "booked"}
DROPPED = {"scraped", "rejected", "cleaned"}  # not kept
SIDE = {"bounced", "suppressed", "unsubscribed"}  # neither success nor failure of enrich, unless the email was verified
EXPLORE_BELOW = 40  # kept leads: a state under this is still unsampled


def tile_scores(stats: dict[str, tuple[int, int]], global_rate: float, prior: int = 20) -> dict[str, float]:
    """stats[key] = (kept, success). Smoothed rate toward the global rate; a key with no stats scores the global rate."""
    out = defaultdict(lambda: global_rate)
    out.update({k: (s + prior * global_rate) / (kn + prior) for k, (kn, s) in stats.items()})
    return out


STATES = dict(zip(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(),
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming".split("|")))
_BY_NAME = {n.lower(): c for c, n in STATES.items()}


def state_code(v) -> str | None:
    """'Texas', 'texas', 'TX' -> 'TX'; None or unknown -> None."""
    v = (v or "").strip()
    return v.upper() if v.upper() in STATES else _BY_NAME.get(v.lower())


def yield_stats(leads: list[dict], owner: dict, tiles: dict):
    """Pure. Per state from ALL leads by normalised leads.state; per metro through owner[batch_id] (the done coverage row),
    only metros with 2+ done tiles; global rate over every kept lead, state known or not."""
    by_state, by_metro = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    kept = won = 0
    for lead in leads:
        verified = bool(lead.get("owner_email") and lead.get("email_verified"))
        if lead["status"] in DROPPED or (lead["status"] in SIDE and not verified):
            continue
        ok = lead["status"] in SUCCESS or (lead["status"] in SIDE and verified)
        kept, won = kept + 1, won + ok
        keys = [(by_state, state_code(lead["state"]))]
        if lead.get("batch_id") in owner:
            keys.append((by_metro, owner[lead["batch_id"]]["metro"]))
        for d, key in keys:
            if key:
                d[key][0] += 1
                d[key][1] += ok
    return ({k: tuple(v) for k, v in by_state.items()},
            {k: tuple(v) for k, v in by_metro.items() if tiles.get(k, 0) >= 2}, won / kept if kept else 0.0)


def load_yield_stats(db) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]], float]:
    """(per state, per metro, global rate), each (kept, success); see yield_stats. Metros join leads to done tiles
    through coverage.scrape_batch_id = leads.batch_id."""
    done = fetch_all(lambda: db.table("coverage").select("id,metro,state,scrape_batch_id").eq("status", "done").order("id"))
    owner = {c["scrape_batch_id"]: c for c in done if c["scrape_batch_id"]}
    leads = fetch_all(lambda: db.table("leads").select("id,state,batch_id,status,owner_email,email_verified").order("id"))
    return yield_stats(leads, owner, Counter(c["metro"] for c in done))


def _pick(pending: list[dict], state_stats, metro_stats, rate: float, explore: bool) -> dict:
    """pending is sorted by seq. Explore: lowest seq in a state with < EXPLORE_BELOW kept leads (else lowest seq).
    Otherwise highest score (metro if it has stats, else state, else global), ties by lowest seq."""
    if explore:
        return next((t for t in pending if state_stats.get(t["state"], (0, 0))[0] < EXPLORE_BELOW), pending[0])
    ss, ms = tile_scores(state_stats, rate), tile_scores(metro_stats, rate)
    return max(pending, key=lambda t: (ms[t["metro"]] if t["metro"] in metro_stats else ss[t["state"]], -t["seq"]))


def claim_tiles(db, n: int, stats=None) -> list[dict]:
    """Flip up to n pending tiles to running. A lost race (row no longer pending) is skipped.
    walk_yield_order off: lowest seq first. On: best smoothed yield first, and every third claim explores.
    ponytail: per-row conditional update, fine for one or two workers."""
    if not setting("walk_yield_order"):
        ids = [c["id"] for c in db.table("coverage").select("id").eq("status", "pending").order("seq").limit(n).execute().data]
    else:
        pending = fetch_all(lambda: db.table("coverage").select("id,seq,metro,state").eq("status", "pending").order("seq"))
        used = db.table("coverage").select("id", count="exact").in_("status", ["running", "done"]).limit(1).execute().count or 0
        state_stats, metro_stats, rate = stats or load_yield_stats(db)
        ids = []
        while pending and len(ids) < n:
            # exploration: coverage rows already running or done, modulo 3 == 2 (every third claim)
            t = _pick(pending, state_stats, metro_stats, rate, (used + len(ids)) % 3 == 2)
            pending.remove(t)
            ids.append(t["id"])
    got = []
    for i in ids:
        got += db.table("coverage").update({"status": "running", "started_at": _now()}).eq("id", i).eq("status", "pending").execute().data
    return got


def release_tile(db, tile_id: str) -> None:
    db.table("coverage").update({"status": "pending"}).eq("id", tile_id).execute()


def reset_stale(db, hours: int = 2) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return len(db.table("coverage").update({"status": "pending"}).eq("status", "running").lt("started_at", cutoff).execute().data)


def run_walk(db, run_actor, tiles: int, queries: list[str] | None = None, max_places: int | None = None, escalate_at: float | None = None, provider: str = "apify") -> dict:
    """Scrape and clean the next uncovered tiles. A query is followed by the next one only while it filled its cap
    (items returned >= escalate_at * max_places, counted before dedupe); the last query also filling it flags the tile saturated."""
    serper = provider == "serper"
    gate, floor = ("serper_maps", 3) if serper else ("apify", MIN_CAP)
    if serper:  # one call returns at most 20 places and the wordings are fixed (docs/NEXT-source-pilot.md)
        queries, max_places = queries or QUERIES, min(max_places or PLACES_PER_CALL, PLACES_PER_CALL)
    queries = queries or [q.strip() for q in setting("walk_queries").split(",") if q.strip()]
    max_places = max_places or setting("walk_max_places")
    escalate_at = setting("walk_escalate_at") if escalate_at is None else escalate_at
    out = {"tiles": 0, "queries": 0, "new": 0, "known": 0, "saturated": 0}
    reset_stale(db)
    stats = load_yield_stats(db) if setting("walk_yield_order") else None  # once per walk, not per claim
    for _ in range(tiles):
        got = claim_tiles(db, 1, stats)  # one at a time: a raise never strands later tiles as running
        if not got:
            break
        t = got[0]
        batch, n, found, new, known, ran = None, 0, 0, 0, 0, 0
        try:
            budget.require(gate, floor)  # before new_batch: a blocked tile leaves no empty batch
            batch = new_batch(db, t["tile"], t["state"], [queries[0]])

            def counted(inp):
                nonlocal n
                items, usd = run_actor(inp)
                n = len(items)
                return items, usd

            full = True
            for q in queries:
                if ran:
                    budget.require(gate, floor)
                a, b = scrape_city(db, counted, t["tile"], t["state"], [q], batch, max_places, provider)
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
