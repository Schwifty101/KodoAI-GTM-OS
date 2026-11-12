"""Measure the search-based owner finder ("owner of <domain>" + model read + Hunter Email Finder) on the 45 Houston domains.
Uses free-plan Hunter keys 1, 3, 4 (1 credit per email found). Prints counts only, never names or emails.
Usage: PYTHONPATH=. uv run python scripts/measure_search_owner.py SCRATCH_DIR"""
import collections as C
import glob
import json
import sys
from urllib.parse import urlparse

from gtm.buyer import pick_buyer
from gtm.config import get_settings
from gtm.hunter import HunterPool
from gtm.llm import complete_json
from gtm.owner_search import search_owner_finder
from gtm.search import serper_search

SKIP = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.")
leads, seen = [], set()
files = [f"{sys.argv[1]}/A_broad_houston.json"] + sorted(glob.glob(f"{sys.argv[1]}/B_*.json")) + sorted(glob.glob(f"{sys.argv[1]}/C_*.json")) + sorted(glob.glob(f"{sys.argv[1]}/D_*.json"))
for f in files:
    for p in json.load(open(f)):
        w = p.get("website")
        dom = urlparse(w).netloc.lower().removeprefix("www.") if w else ""
        if dom and dom not in seen and not any(s in dom for s in SKIP) and "Medical spa" in (p.get("categories") or []):
            seen.add(dom)
            leads.append({"domain": dom, "name": p["title"], "city": p.get("city")})
leads = leads[:45]
keys = get_settings().hunter_keys
pool = HunterPool([keys[0], keys[2], keys[3]])
orig = pool.email_finder
stats = C.Counter()
ver = C.Counter()


def counted(domain, first, last):
    stats["hunter_finder_calls"] += 1
    c = orig(domain, first, last)
    if c:
        stats["hunter_returned_email"] += 1
        ver[c.get("verification_status")] += 1
    return c


pool.email_finder = counted
finder = search_owner_finder(pool, serper_search, complete_json)
kinds = C.Counter()
for lead in leads:
    stats["domains"] += 1
    try:
        cands = finder(lead)
    except Exception as e:  # keep measuring; report at the end
        stats["errors"] += 1
        print("error:", type(e).__name__, str(e)[:120])
        continue
    if cands:
        stats["owner_found_and_email_found"] += 1
        host = urlparse(cands[0]["evidence_url"]).netloc.removeprefix("www.")
        kinds["linkedin" if "linkedin" in host else "own/other site" if host else "?"] += 1
        if pick_buyer(cands):
            stats["verified_decision_maker"] += 1
print(dict(stats))
print("verification status of Hunter email-finder results:", dict(ver))
print("evidence source:", dict(kinds))
