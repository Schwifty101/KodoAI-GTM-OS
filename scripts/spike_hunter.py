"""Spike B: Hunter Domain Search on a few med spa domains. Measures credits per call and result quality.
Prints counts, titles and verification only; no personal emails are printed or stored.
Usage: PYTHONPATH=. uv run python scripts/spike_hunter.py SCRATCH_DIR
"""
import json
import sys
from urllib.parse import urlparse

import httpx

from gtm.config import get_settings
from gtm.costs import log_cost

key = get_settings().hunter_keys[0]
H = {"X-API-KEY": key}
API = "https://api.hunter.io/v2"
SKIP = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.")


def credits() -> float:
    d = httpx.get(f"{API}/account", headers=H, timeout=30).json()["data"]["requests"]["credits"]
    return float(d["used"])


places = json.load(open(f"{sys.argv[1]}/A_broad_houston.json"))
doms, seen = [], set()
for p in places:
    if "medical spa" not in (p.get("categoryName") or "").lower() or not p.get("website"):
        continue
    dom = urlparse(p["website"]).netloc.lower().removeprefix("www.")
    if dom and dom not in seen and not any(s in dom for s in SKIP):
        seen.add(dom)
        doms.append(dom)
    if len(doms) == 5:
        break


def search(dom: str, **params) -> dict:
    before = credits()
    r = httpx.get(f"{API}/domain-search", headers=H, params={"domain": dom, "limit": 10, **params}, timeout=60)
    after = credits()
    j = r.json()
    emails = (j.get("data") or {}).get("emails", [])
    log_cost("hunter", after - before, None, note=f"spike:domain-search:{dom}")
    print(f"{dom} {params or ''}: http={r.status_code} credits_used={after - before} emails={len(emails)} "
          f"accept_all={(j.get('data') or {}).get('accept_all')} total_in_meta={(j.get('meta') or {}).get('results')}")
    for e in emails:
        print(f"   type={e.get('type')} pos={e.get('position')!r} seniority={e.get('seniority')} dept={e.get('department')} "
              f"conf={e.get('confidence')} verif={(e.get('verification') or {}).get('status')} email_is_role={str(e.get('value','')).split('@')[0] in ('info','contact','hello','office','admin','support')}")
    return j


for d in doms:
    search(d)
search(doms[0], seniority="senior,executive", type="personal")
search(doms[1], seniority="senior,executive", type="personal")
print("credits used total on key 1 this spike:", credits())
