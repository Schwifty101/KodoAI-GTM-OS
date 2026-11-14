"""Verify gtm/data/metros.csv tiles against the Google Maps Geocoding API.

Run: uv run python -m scripts.verify_tiles [--limit N] [--out FILE] [--dry-run]
Query is '<tile>, <ST>, USA' with components=country:US. Key: GOOGLE_MAPS_API_KEY (gtm/config.py), never printed.

Price (Google pricing page, checked 2026-11-14; https://developers.google.com/maps/billing-and-pricing/pricing):
Geocoding is an Essentials SKU, $5.00 per 1,000 requests for the first 100k/month, 10,000 free billable events per month.
So all 1285 tiles fit in the free allowance; list price would be about $6.43. Not cross-confirmed on a second page.

Flags: status (not OK), state_mismatch (admin_area_level_1 != CSV state), partial_match, bad_type
(none of ALLOWED_TYPES), too_far (haversine miles from the metro's principal city, the first CSV row of the
metro, over 60 for rank <= 35 else 45; a heuristic, not a metro boundary; tile state != principal state is fine).
The principal city is itself geocoded (cached), and counts as one extra request per metro.
Results cache to <out>.cache.json so reruns make no calls.
"""
import argparse
import csv
import json
import math
import time
from collections import Counter
from pathlib import Path

import httpx

from gtm.config import get_settings

URL = "https://maps.googleapis.com/maps/api/geocode/json"
METROS = Path(__file__).resolve().parent.parent / "gtm/data/metros.csv"
PRICE_PER_1000, FREE = 5.0, 10_000
# Sensible place types for a tile that is a city, town, district or neighborhood.
ALLOWED_TYPES = {"locality", "sublocality", "sublocality_level_1", "neighborhood", "administrative_area_level_3",
                 "administrative_area_level_4", "postal_town", "colloquial_area"}
# ponytail: counties (administrative_area_level_2) are flagged bad_type; add if tiles are intentionally counties.


def haversine(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def classify(data, state, principal, max_miles):
    """principal: (lat, lng) or None. Returns dict with status, formatted_address, lat, lng, distance_miles, flags."""
    out = {"status": data.get("status", "ERROR"), "formatted_address": "", "lat": "", "lng": "", "distance_miles": "", "flags": []}
    if out["status"] != "OK" or not data.get("results"):
        out["flags"].append("status")
        return out
    r = data["results"][0]
    loc = r["geometry"]["location"]
    out.update(formatted_address=r.get("formatted_address", ""), lat=loc["lat"], lng=loc["lng"])
    st = next((c["short_name"] for c in r.get("address_components", []) if "administrative_area_level_1" in c["types"]), None)
    if st != state:
        out["flags"].append("state_mismatch")
    if r.get("partial_match"):
        out["flags"].append("partial_match")
    if not ALLOWED_TYPES & set(r.get("types", [])):
        out["flags"].append("bad_type")
    if principal:
        out["distance_miles"] = round(haversine(loc["lat"], loc["lng"], *principal), 1)
        if out["distance_miles"] > max_miles:
            out["flags"].append("too_far")
    return out


def fetch(client, key, tile, state):
    try:
        r = client.get(URL, params={"address": f"{tile}, {state}, USA", "components": "country:US", "key": key}, timeout=20)
        return r.json()
    except Exception as e:  # never raise; record and move on
        return {"status": f"ERROR:{type(e).__name__}", "results": []}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="tile_report.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    rows = list(csv.DictReader(METROS.open()))[: a.limit]
    principal_row = {}
    for r in rows:
        principal_row.setdefault(r["metro"], r)
    cache_path = Path(a.out + ".cache.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    keys = {(r["tile"], r["state"]) for r in rows} | {(p["tile"], p["state"]) for p in principal_row.values()}
    todo = [k for k in keys if f"{k[0]}|{k[1]}" not in cache]
    cost = max(0, len(todo) - FREE) * PRICE_PER_1000 / 1000
    if a.dry_run:
        print(f"{len(todo)} requests ({len(keys) - len(todo)} cached); estimated cost ${cost:.2f} after the {FREE} free/month "
              f"(list price ${len(todo) * PRICE_PER_1000 / 1000:.2f})")
        return
    key = get_settings().google_maps_api_key
    if todo and not key:
        raise SystemExit("GOOGLE_MAPS_API_KEY not set")
    with httpx.Client() as client:
        for i, (tile, st) in enumerate(sorted(todo)):
            cache[f"{tile}|{st}"] = fetch(client, key, tile, st)
            if i % 25 == 0:
                cache_path.write_text(json.dumps(cache))
            time.sleep(0.05)  # ~20 req/s, well under Google's limit
    cache_path.write_text(json.dumps(cache))

    def loc(tile, st):
        d = cache.get(f"{tile}|{st}", {})
        return (lambda l: (l["lat"], l["lng"]))(d["results"][0]["geometry"]["location"]) if d.get("status") == "OK" and d.get("results") else None

    report = []
    for r in rows:
        p = principal_row[r["metro"]]
        miles = 60 if int(r["metro_rank"]) <= 35 else 45
        c = classify(cache[f"{r['tile']}|{r['state']}"], r["state"], loc(p["tile"], p["state"]), miles)
        report.append({"metro": r["metro"], "state": r["state"], "tile": r["tile"], **c, "flags": ";".join(c["flags"])})
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, ["metro", "state", "tile", "status", "formatted_address", "lat", "lng", "distance_miles", "flags"])
        w.writeheader()
        w.writerows(report)
    counts = Counter(fl for x in report for fl in x["flags"].split(";") if fl)
    print(f"{len(report)} tiles, {sum(1 for x in report if x['flags'])} flagged; per flag: {dict(counts)}")
    far = sorted((x for x in report if x["distance_miles"] != ""), key=lambda x: -x["distance_miles"])[:10]
    for x in far:
        print(f"  {x['distance_miles']:>7} mi  {x['tile']}, {x['state']} ({x['metro']})  [{x['flags']}]")


if __name__ == "__main__":
    main()
