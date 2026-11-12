"""Spike A: one-city Apify run. Measures price per place, website share, filter behaviour, coverage.

Spends real money, capped per run via maxTotalChargeUsd. Items go to the scratchpad, not the repo.
Usage: uv run python scripts/spike_apify.py SCRATCH_DIR
"""
import json
import sys
import time
from pathlib import Path

import httpx

from gtm.config import get_settings
from gtm.costs import log_cost

ACTOR = "compass~crawler-google-places"
API = "https://api.apify.com/v2"
scratch = Path(sys.argv[1])
scratch.mkdir(parents=True, exist_ok=True)
H = {"Authorization": f"Bearer {get_settings().apify_keys[1]}"}  # the $10 free key


def run(label: str, run_input: dict, cap: float) -> tuple[list[dict], dict]:
    r = httpx.post(f"{API}/acts/{ACTOR}/runs", params={"maxTotalChargeUsd": cap}, headers=H, json=run_input, timeout=60)
    r.raise_for_status()
    info = r.json()["data"]
    while info["status"] in ("READY", "RUNNING"):
        time.sleep(5)
        info = httpx.get(f"{API}/actor-runs/{info['id']}", headers=H, timeout=60).json()["data"]
    items = httpx.get(f"{API}/datasets/{info['defaultDatasetId']}/items", params={"clean": "true"}, headers=H, timeout=120).json()
    (scratch / f"{label}.json").write_text(json.dumps(items))
    usd = info.get("usageTotalUsd")
    log_cost("apify", len(items), usd, note=f"spike:{label}")
    print(f"{label}: status={info['status']} items={len(items)} usd={usd} events={info.get('chargedEventCounts')}")
    return items, info


base = {"searchStringsArray": ["med spa"], "countryCode": "us", "language": "en", "skipClosedPlaces": False}
fa = scratch / "A_broad_houston.json"
if fa.exists():  # already bought once ($0.4802); do not pay twice
    a = json.loads(fa.read_text())
else:
    a, _ = run("A_broad_houston", {**base, "locationQuery": "Houston, TX, USA", "maxCrawledPlacesPerSearch": 120}, 1.00)
tiles = ["Sugar Land, TX, USA", "The Woodlands, TX, USA"]  # Apify minimum cap is $0.50 per run
b = []
for t in tiles:
    items, _ = run(f"B_{t.split(',')[0].replace(' ', '_')}", {**base, "locationQuery": t, "maxCrawledPlacesPerSearch": 40, "website": "withWebsite"}, 0.50)
    b += items

pid = lambda x: x.get("placeId")
ap, bp = {pid(x) for x in a}, {pid(x) for x in b}
print("A unique", len(ap), "| with website", sum(1 for x in a if x.get("website")), "| fields", sorted(a[0]) if a else None)
print("B unique", len(bp), "| with website", sum(1 for x in b if x.get("website")), "of", len(b))
print("B not in A:", len(bp - ap), "| overlap:", len(ap & bp))
print("A cities:", sorted({x.get("city") for x in a if x.get("city")})[:15])
print("A top categories:", sorted({(x.get("categoryName") or "?") for x in a})[:15])
