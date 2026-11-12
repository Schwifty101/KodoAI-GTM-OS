"""Task 1b tile tuning spike. Measures query depth per tile; writes only cost_log rows, never leads or batches.
Usage: uv run python -m scripts.tile_tuning --tiles "Plano,TX;Scottsdale,AZ;..." [--probe-tiles "Plano,TX;..."] [--dry-run] [--out FILE]
SPENDS APIFY MONEY unless --dry-run. Owner gate: Task 1b step 3.
"""
import argparse
import json
import os
from collections import defaultdict

from gtm import apify, budget, scrape
from gtm.clean import clean_decision
from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.db import get_db

QUERIES = ["med spa", "aesthetics clinic", "botox"]
CAP, RUN_USD, STOP_BELOW = 40, 0.50, 36  # stop a tile when a query returns < 0.9 x cap
WORST = 0.005 * CAP  # per-query estimate at $0.005 per place


def parse_tiles(s: str) -> list[tuple[str, str]]:
    return [tuple(p.strip() for p in t.split(",")) for t in s.split(";") if t.strip()]


def known_ids(db, ids: list[str]) -> set[str]:
    out: set[str] = set()
    for i in range(0, len(ids), 100):
        out |= {r["place_id"] for r in db.table("leads").select("place_id").in_("place_id", ids[i : i + 100]).execute().data}
    return out


def measure(db, city, state, pos, seen, query, items, usd) -> dict:
    # clean_decision gets place_to_lead rows (the same shape run_clean reads); batch-level rules
    # (brand repeats, duplicate domains) are not applied. ponytail: approximation, slightly over-counts kept.
    places = {it["placeId"]: scrape.place_to_lead(it, "") for it in items if it.get("placeId")}
    in_leads = known_ids(db, list(places))
    fresh = [p for p in places if p not in seen]  # new versus earlier queries on this tile
    new = [p for p in fresh if p not in in_leads]
    kept = [p for p in new if clean_decision(places[p]) is None]
    seen |= set(places)
    usd = usd or 0.0
    return {"city": city, "state": state, "pos": pos, "query": query, "places": len(items), "cap_hit": len(items) == CAP,
            "new_vs_earlier": len(fresh), "new_vs_leads": len(places) - len(in_leads), "new": len(new),
            "new_kept": len(kept), "usd": usd, "kept_per_usd": round(len(kept) / usd, 1) if usd else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", required=True)
    ap.add_argument("--probe-tiles", help="default: the first two tiles; these always run all three queries")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.environ.get("GTM_SCRATCH", "./scripts"), "tile_tuning_out.json"))
    a = ap.parse_args()
    tiles = parse_tiles(a.tiles)
    probe = parse_tiles(a.probe_tiles) if a.probe_tiles else tiles[:2]
    assert set(probe) <= set(tiles), "--probe-tiles must be a subset of --tiles"
    full = len(probe) * len(QUERIES) + (len(tiles) - len(probe))  # non-probe tiles: at least one query
    worst = len(tiles) * len(QUERIES) * WORST
    print(f"tiles={tiles}\nprobe (all 3 queries)={probe}\nqueries={QUERIES} cap={CAP} per-run cap=${RUN_USD}")
    print(f"min runs {full}, max runs {len(tiles) * len(QUERIES)}, worst-case about ${worst:.2f} (${WORST:.2f}/query)")
    keys = get_settings().apify_keys
    if keys:
        print("Apify remaining:", {f"key{i}": round(apify.remaining_usd(k), 2) for i, k in enumerate(keys)})
    if a.dry_run:
        return
    db, rows = get_db(), []
    for city, state in tiles:
        seen: set[str] = set()
        tile_rows: list[dict] = []
        for q in QUERIES:
            budget.require("apify", RUN_USD)
            items, usd = apify.run_places(scrape.scrape_input(city, state, [q], CAP), RUN_USD)
            log_cost("apify", len(items), usd, note="spike:tile_tuning")
            tile_rows.append(measure(db, city, state, len(tile_rows) + 1, seen, q, items, usd))
            if len(items) < STOP_BELOW and (city, state) not in probe:
                break
        rows += tile_rows
        print(f"\n== {city}, {state}")
        print(f"{'#':>2} {'query':<18}{'places':>7}{'cap':>5}{'new/tile':>9}{'new/leads':>10}{'new':>5}{'kept':>5}{'usd':>8}{'kept/$':>8}")
        for r in tile_rows:
            print(f"{r['pos']:>2} {r['query']:<18}{r['places']:>7}{'Y' if r['cap_hit'] else '-':>5}{r['new_vs_earlier']:>9}"
                  f"{r['new_vs_leads']:>10}{r['new']:>5}{r['new_kept']:>5}{r['usd']:>8.4f}{str(r['kept_per_usd']):>8}")
    by = defaultdict(lambda: [0, 0.0])
    for r in rows:
        by[r["pos"]][0] += r["new_kept"]
        by[r["pos"]][1] += r["usd"]
    print("\nMarginal new kept per dollar by query position (new = not earlier on tile, not in leads):")
    for pos, (k, u) in sorted(by.items()):
        print(f"  position {pos} ({QUERIES[pos - 1]}): kept {k}, ${u:.4f}, {k / u:.1f} per $" if u else f"  position {pos}: no spend")
    with open(a.out, "w") as f:
        json.dump(rows, f, indent=1)
    print("raw rows:", a.out)


if __name__ == "__main__":
    main()
