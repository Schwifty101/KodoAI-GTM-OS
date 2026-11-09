"""Re-run the owner search on the 45 domains WITHOUT calling Hunter, saving (domain, first, last, title) to the scratchpad only,
so other email finders can be tested on the same names. Names are personal data: never committed, never printed.
Usage: PYTHONPATH=. uv run python scripts/capture_owner_names.py SCRATCH_DIR"""
import glob
import json
import sys
from urllib.parse import urlparse

from gtm.llm import complete_json
from gtm.owner_search import search_owner_finder
from gtm.search import serper_search

SKIP = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.")
leads, seen = [], set()
for f in [f"{sys.argv[1]}/A_broad_houston.json"] + sorted(glob.glob(f"{sys.argv[1]}/B_*.json")) + sorted(glob.glob(f"{sys.argv[1]}/C_*.json")) + sorted(glob.glob(f"{sys.argv[1]}/D_*.json")):
    for p in json.load(open(f)):
        w = p.get("website")
        dom = urlparse(w).netloc.lower().removeprefix("www.") if w else ""
        if dom and dom not in seen and not any(s in dom for s in SKIP) and "Medical spa" in (p.get("categories") or []):
            seen.add(dom)
            leads.append({"domain": dom, "name": p["title"], "city": p.get("city")})
leads = leads[:45]


class Capture:
    def __init__(self):
        self.pairs = []

    def email_finder(self, domain, first, last):
        self.pairs.append({"domain": domain, "first": first, "last": last})
        return None


cap = Capture()
finder = search_owner_finder(cap, serper_search, complete_json)
for lead in leads:
    try:
        finder(lead)
    except Exception as e:
        print("error", type(e).__name__)
json.dump(cap.pairs, open(f"{sys.argv[1]}/owner_names.json", "w"))
print("captured", len(cap.pairs), "owner names on", len(leads), "domains")
