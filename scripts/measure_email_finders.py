"""Compare Prospeo and Tomba name+domain email finders on the captured owner names (scratchpad only).
Prints counts only. Prospeo: 1 credit per email found, free on no match. Tomba: cost unstated; capped at --tomba N calls.
Usage: PYTHONPATH=. uv run python scripts/measure_email_finders.py SCRATCH_DIR [--tomba N]"""
import collections as C
import json
import sys

import httpx
from dotenv import dotenv_values

env = dotenv_values(".env")
pairs = json.load(open(f"{sys.argv[1]}/owner_names.json"))
tomba_cap = int(sys.argv[sys.argv.index("--tomba") + 1]) if "--tomba" in sys.argv else 0
pro, tom = C.Counter(), C.Counter()
pro_status, tom_status = C.Counter(), C.Counter()
shown_keys = None
for i, p in enumerate(pairs):
    r = httpx.post("https://api.prospeo.io/enrich-person", headers={"X-KEY": env["PROSPEO_API_KEY"], "Content-Type": "application/json"},
                   json={"only_verified_email": True, "data": {"first_name": p["first"], "last_name": p["last"], "company_website": p["domain"]}}, timeout=60)
    pro["calls"] += 1
    j = r.json()
    if r.status_code != 200 or j.get("error"):
        pro["errors"] += 1
        pro_status[str(j.get("error_code") or r.status_code)] += 1
    else:
        em = (j.get("person") or {}).get("email") or {}
        if shown_keys is None:
            shown_keys = sorted(em)
        if em.get("email"):
            pro["found"] += 1
            pro["unmasked"] += "*" not in em["email"]
            pro_status[em.get("status")] += 1
    if i < tomba_cap:
        r = httpx.get("https://api.tomba.io/v1/email-finder", headers={"X-Tomba-Key": env["TOMBA_API_KEY"], "X-Tomba-Secret": env["TOMBA_API_SECRET"]},
                      params={"domain": p["domain"], "first_name": p["first"], "last_name": p["last"]}, timeout=60)
        tom["calls"] += 1
        d = (r.json().get("data") or {}) if r.status_code == 200 else {}
        if r.status_code != 200:
            tom["errors"] += 1
            tom_status[str(r.status_code)] += 1
        elif d.get("email"):
            tom["found"] += 1
            tom_status[(d.get("verification") or {}).get("status")] += 1
print("prospeo", dict(pro), dict(pro_status), "| email object keys:", shown_keys)
print("tomba", dict(tom), dict(tom_status))
