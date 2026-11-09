"""Spike B2: yield of Hunter Domain Search over ~40 med spa domains (key 3). Aggregates only; no emails printed.
Usage: PYTHONPATH=. uv run python scripts/spike_hunter_bulk.py SCRATCH_DIR
"""
import collections as C
import glob
import json
import re
import sys
from urllib.parse import urlparse

import httpx

from gtm.config import get_settings
from gtm.costs import log_cost

H = {"X-API-KEY": get_settings().hunter_keys[2]}
API = "https://api.hunter.io/v2"
SKIP = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.")
DM = re.compile(r"\b(founder|owner|co-?owner|ceo|chief executive|president|principal|proprietor)\b", re.I)


def used() -> float:
    return float(httpx.get(f"{API}/account", headers=H, timeout=30).json()["data"]["requests"]["credits"]["used"])


places = [p for f in sorted(glob.glob(f"{sys.argv[1]}/*.json")) for p in json.load(open(f))]
doms, seen = [], {"psmedspa.com", "medspaofkingwood.net", "renovemedicalspa.com", "kingwoodskinessentials.com", "medispatexas.com"}
for p in places:
    if not p.get("website"):
        continue
    d = urlparse(p["website"]).netloc.lower().removeprefix("www.")
    if d and d not in seen and not any(s in d for s in SKIP):
        seen.add(d)
        doms.append(d)
    if len(doms) == 40:
        break

t = C.Counter()
start = used()
for d in doms:
    b = used()
    j = httpx.get(f"{API}/domain-search", headers=H, params={"domain": d, "limit": 10}, timeout=60).json()
    a = used()
    em = (j.get("data") or {}).get("emails", [])
    t["domains"] += 1
    t["credits"] += a - b
    if em:
        t["any_email"] += 1
    pers = [e for e in em if e.get("type") == "personal"]
    if pers:
        t["personal_email"] += 1
    ver = [e for e in pers if (e.get("verification") or {}).get("status") == "valid"]
    if ver:
        t["personal_verified"] += 1
    dm = [e for e in em if DM.search(e.get("position") or "")]
    if dm:
        t["dm_title"] += 1
    if [e for e in dm if (e.get("verification") or {}).get("status") == "valid"]:
        t["dm_title_verified"] += 1
    if (j.get("data") or {}).get("accept_all"):
        t["accept_all_domain"] += 1
    t["emails_total"] += len(em)
    for e in em:
        t["pos:" + str((e.get("position") or "none")).lower()[:30]] += 1
log_cost("hunter", used() - start, None, note="spike:bulk-40")
for k, v in t.items():
    if not k.startswith("pos:"):
        print(k, v)
print("top positions:", [(k[4:], v) for k, v in t.most_common() if k.startswith("pos:")][:10])
print("credits used on key 3 now:", used())
