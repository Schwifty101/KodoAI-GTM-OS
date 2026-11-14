"""Read-only A/B on one tile: Serper Maps vs Apify. Writes only cost_log rows (real spend), no leads.
Usage: uv run python scripts/ab_serper_apify.py CITY STATE OUT.json  (docs/NEXT-source-pilot.md)"""
import json
import sys

from gtm.apify import MIN_CAP, run_places
from gtm.clean import clean_decision
from gtm.costs import log_cost
from gtm.db import get_db
from gtm.scrape import place_to_lead, scrape_input
from gtm.serper_maps import CREDITS_PER_CALL, PLACES_PER_CALL, QUERIES, serper_maps

city, state, out = sys.argv[1:4]
APIFY_QUERIES = ["med spa", "aesthetics clinic"]  # walk defaults


def serper_side():
    items, calls = {}, 0
    for q in QUERIES:
        got = serper_maps(f"{q} {city}, {state}, USA")
        log_cost("serper_maps", CREDITS_PER_CALL, None, note=f"ab:{q}")
        calls += 1
        items.update({i["placeId"]: i for i in got})
        if len(got) < 0.8 * PLACES_PER_CALL:
            break
    return items, {"calls": calls, "credits": calls * CREDITS_PER_CALL, "usd": calls * CREDITS_PER_CALL * 0.001}


def apify_side():
    items, usd = {}, 0.0
    for q in APIFY_QUERIES:
        got, u = run_places(scrape_input(city, state, [q], 40), MIN_CAP)
        log_cost("apify", len(got), u, note=f"ab:{q}")
        usd += u or 0
        items.update({i["placeId"]: i for i in got if i.get("placeId")})
    return items, {"queries": len(APIFY_QUERIES), "usd": usd}


s_items, s_cost = serper_side()
a_items, a_cost = apify_side()
db = get_db()
ids = list(set(s_items) | set(a_items))
known = {r["place_id"] for i in range(0, len(ids), 100) for r in db.table("leads").select("place_id").in_("place_id", ids[i:i + 100]).execute().data}


def kept(items):
    return {p for p, it in items.items() if clean_decision(place_to_lead(it, "ab")) is None}


sk, ak = kept(s_items), kept(a_items)
res = {"tile": f"{city} {state}", "serper": {**s_cost, "unique": len(s_items), "kept": len(sk), "kept_new": len(sk - known)},
       "apify": {**a_cost, "unique": len(a_items), "kept": len(ak), "kept_new": len(ak - known)},
       "kept_overlap": len(sk & ak), "serper_only_kept": len(sk - ak), "apify_only_kept": len(ak - sk)}
json.dump({**res, "serper_items": s_items, "apify_names": {p: a_items[p].get("title") for p in a_items}}, open(out, "w"), indent=1, default=str)
print(json.dumps(res, indent=1))
