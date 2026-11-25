"""Read-only yield report. Usage: uv run python -m scripts.yield_report
Autopilot runs are not stored, so a "run" here is a UTC day with at least one `walk` job. Prints counts and 8-char batch prefixes only."""
from collections import defaultdict

from gtm.db import fetch_all, get_db

DROPPED = {"scraped", "rejected", "cleaned"}
ENRICHED = {"enriched", "signalled", "selected", "drafted", "sent", "replied", "booked"}


def _rate(n, d):
    return n / d if d else None


def _fmt(x, nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}"


def summarise(leads: list[dict], cost_rows: list[dict], jobs: list[dict]) -> dict:
    """leads carry batch_id, batch_created_at, batch_query (joined from batches by main())."""
    kept = lambda l: l["status"] not in DROPPED  # noqa: E731
    enr = lambda l: l["status"] in ENRICHED  # noqa: E731
    states: dict = defaultdict(lambda: {"kept": 0, "enriched": 0})
    runs: dict = {}
    enriched_by_day: dict = defaultdict(int)
    for l in leads:
        s = states[l.get("state") or "?"]
        r = runs.setdefault(l["batch_id"], {"batch": (l["batch_id"] or "none")[:8], "created": (l.get("batch_created_at") or "")[:10],
                                            "query": l.get("batch_query") or "", "scraped": 0, "kept": 0, "named": 0, "enriched": 0})
        r["scraped"] += 1
        if kept(l):
            s["kept"] += 1
            r["kept"] += 1
            r["named"] += bool(l.get("owner_name"))
        if enr(l):
            s["enriched"] += 1
            r["enriched"] += 1
            enriched_by_day[r["created"]] += 1
    for s in states.values():
        s["rate"] = _rate(s["enriched"], s["kept"])
    spend: dict = defaultdict(float)
    for c in cost_rows:
        spend[c["created_at"][:10]] += float(c.get("usd") or 0)
    days = []
    for d in sorted({j["created_at"][:10] for j in jobs if j["kind"] == "walk"}):
        days.append({"day": d, "usd": spend[d], "enriched": enriched_by_day[d], "per_usd": _rate(enriched_by_day[d], spend[d])})
    k = sum(s["kept"] for s in states.values())
    e = sum(s["enriched"] for s in states.values())
    return {"kept": k, "enriched": e, "rate": _rate(e, k), "states": dict(states),
            "runs": sorted(runs.values(), key=lambda r: r["created"]), "days": days}


def main() -> None:
    db = get_db()
    batches = {b["id"]: b for b in fetch_all(lambda: db.table("batches").select("id,created_at,query").order("id"))}
    leads = fetch_all(lambda: db.table("leads").select("id,status,state,batch_id,owner_name").order("id"))
    for l in leads:
        b = batches.get(l["batch_id"]) or {}
        l["batch_created_at"], l["batch_query"] = b.get("created_at"), b.get("query")
    cost = fetch_all(lambda: db.table("cost_log").select("id,usd,created_at").order("id"))
    jobs = fetch_all(lambda: db.table("jobs").select("id,kind,created_at").eq("kind", "walk").order("id"))
    s = summarise(leads, cost, jobs)
    print(f"kept {s['kept']}, enriched {s['enriched']}, rate {_fmt(s['rate'], 3)}")
    print("\nPer state: kept, enriched, rate")
    for st, v in sorted(s["states"].items(), key=lambda kv: -kv[1]["kept"]):
        print(f"  {st:<4}{v['kept']:>6}{v['enriched']:>6}{_fmt(v['rate'], 3):>8}")
    print("\nPer scrape run: batch, created, query, scraped, kept, named, enriched, rate")
    for r in s["runs"]:
        print(f"  {r['batch']}  {r['created']}  {r['query'][:20]:<20}{r['scraped']:>6}{r['kept']:>6}{r['named']:>6}{r['enriched']:>6}{_fmt(_rate(r['enriched'], r['kept']), 3):>8}")
    print("\nPer autopilot run (autopilot runs are not stored: runs = UTC days with a walk job; enriched = leads of scrape runs created that day)")
    print("  day, usd (all cost_log that day), enriched, enriched per usd")
    for d in s["days"]:
        print(f"  {d['day']}  ${d['usd']:>7.2f}{d['enriched']:>6}{_fmt(d['per_usd']):>8}")


if __name__ == "__main__":
    main()
