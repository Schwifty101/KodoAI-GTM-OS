"""Measure the owner-name lever on the same 45 Houston domains as the Hunter spike. Step 1 is free (HTTP only).
Usage: PYTHONPATH=. uv run python scripts/measure_site_owner.py SCRATCH_DIR [--hunter N]
  --hunter N also runs Hunter Email Finder for up to N found names (1 credit each when found), on free-plan keys 1, 3, 4.
Prints counts and titles only, never names or emails."""
import collections as C
import json
import sys
from urllib.parse import urlparse

from gtm.config import get_settings
from gtm.enrich import pick_buyer
from gtm.hunter import HunterPool
from gtm.sitescrape import find_owner_candidates, http_fetch

d = sys.argv[1]
budget = int(sys.argv[sys.argv.index("--hunter") + 1]) if "--hunter" in sys.argv else 0
SKIP = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.")
places = json.load(open(f"{d}/A_broad_houston.json"))
doms, seen = [], set()
for p in places:  # first 5 as in spike_hunter.py, then the next 40 as in spike_hunter_bulk.py, restricted to what both used
    if "medical spa" in (p.get("categoryName") or "").lower() and p.get("website"):
        dom = urlparse(p["website"]).netloc.lower().removeprefix("www.")
        if dom and dom not in seen and not any(s in dom for s in SKIP):
            seen.add(dom)
            doms.append(dom)
    if len(doms) == 5:
        break
import glob  # noqa: E402
for f in sorted(glob.glob(f"{d}/*.json")):
    for p in json.load(open(f)):
        w = p.get("website")
        dom = urlparse(w).netloc.lower().removeprefix("www.") if w else ""
        if dom and dom not in seen and not any(s in dom for s in SKIP):
            seen.add(dom)
            doms.append(dom)
        if len(doms) == 45:
            break
    if len(doms) == 45:
        break

keys = get_settings().hunter_keys
pool = HunterPool([keys[0], keys[2], keys[3]], log=lambda u, n: None)
t = C.Counter()
titles = C.Counter()
for dom in doms:
    names = find_owner_candidates(dom, http_fetch)
    t["domains"] += 1
    if names:
        t["site_found_decision_maker_name"] += 1
        titles.update(n["position"].lower() for n in names)
    if names and t["finder_calls"] < budget:
        for n in names[:2]:
            c = pool.email_finder(dom, n["first_name"], n["last_name"])
            t["finder_calls"] += 1
            if c:
                t["finder_returned_email"] += 1
                if pick_buyer([{**c, "position": n["position"]}]):
                    t["verified_decision_maker"] += 1
                    break
print(dict(t))
print("titles found on sites:", titles.most_common(8))
