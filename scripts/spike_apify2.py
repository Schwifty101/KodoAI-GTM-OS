"""Spike A2: query optimisation on the Sugar Land tile. Compares precision, recall and cost against run B_Sugar_Land.
Spend is capped per run ($0.50 each, Apify's minimum). Usage: PYTHONPATH=. uv run python scripts/spike_apify2.py SCRATCH_DIR
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.argv = [sys.argv[0], sys.argv[1]]
scratch = Path(sys.argv[1])

import httpx  # noqa: E402

from gtm.config import get_settings  # noqa: E402
from gtm.costs import log_cost  # noqa: E402

ACTOR, API = "compass~crawler-google-places", "https://api.apify.com/v2"
H = {"Authorization": f"Bearer {get_settings().apify_keys[1]}"}


def run(label, inp, cap=0.50):
    import time
    r = httpx.post(f"{API}/acts/{ACTOR}/runs", params={"maxTotalChargeUsd": cap}, headers=H, json=inp, timeout=60)
    r.raise_for_status()
    info = r.json()["data"]
    while info["status"] in ("READY", "RUNNING"):
        time.sleep(5)
        info = httpx.get(f"{API}/actor-runs/{info['id']}", headers=H, timeout=60).json()["data"]
    items = httpx.get(f"{API}/datasets/{info['defaultDatasetId']}/items", params={"clean": "true"}, headers=H, timeout=120).json()
    (scratch / f"{label}.json").write_text(json.dumps(items))
    ev = {k: v for k, v in (info.get("chargedEventCounts") or {}).items() if v}
    log_cost("apify", len(items), info.get("usageTotalUsd"), note=f"spike2:{label}")
    print(f"{label}: items={len(items)} usd={info.get('usageTotalUsd')} events={ev}")
    return items


ok = lambda x: "Medical spa" in (x.get("categories") or []) or bool(re.search(r"med ?spa|medical spa|aesthetic", x["title"].lower()))
base = json.load(open(scratch / "B_Sugar_Land.json"))
bids = {x["placeId"] for x in base}
common = {"countryCode": "us", "language": "en", "locationQuery": "Sugar Land, TX, USA", "website": "withWebsite"}

fc = scratch / "C_multi_query.json"
c = json.loads(fc.read_text()) if fc.exists() else run("C_multi_query", {**common, "searchStringsArray": ["medspa", "medical spa", "botox", "aesthetics clinic"], "maxCrawledPlacesPerSearch": 20})
d = run("D_category_filter", {**common, "searchStringsArray": ["med spa"], "maxCrawledPlacesPerSearch": 40, "categoryFilterWords": ["medical spa", "health spa", "skin care clinic", "laser hair removal service", "facial spa"]})
for name, S in (("B baseline (med spa)", base), ("C multi-query", c), ("D categoryFilterWords", d)):
    good = [x for x in S if ok(x)]
    print(f"{name}: {len(S)} places, {len(good)} on-ICP ({round(100*len(good)/max(len(S),1))}%), new vs baseline: {len({x['placeId'] for x in S}-bids)}")
allgood = {x["placeId"] for S in (base, c, d) for x in S if ok(x)}
print("union of on-ICP places across all three:", len(allgood), "| baseline alone:", len({x['placeId'] for x in base if ok(x)}))
by = {}
for x in c:
    by.setdefault(x.get("searchString"), []).append(x)
print("C by query:", {k: f"{sum(ok(x) for x in v)}/{len(v)} on-ICP" for k, v in by.items()})
