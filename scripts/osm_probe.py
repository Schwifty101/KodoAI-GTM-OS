"""Probe: can OpenStreetMap (Overpass) feed med-spa discovery? Read-only on the DB. Run: uv run python scripts/osm_probe.py"""
import difflib, json, re, sys, time, urllib.parse, urllib.request
sys.path.insert(0, ".")
from gtm.clean import clean_decision
from gtm.db import fetch_all, get_db
from gtm.scrape import _domain

AREAS = {"Manhattan NY": (40.70, -74.02, 40.88, -73.91), "Cary NC area": (35.67, -78.95, 35.85, -78.65),
         "Bluffton/Hilton Head SC": (32.10, -81.00, 32.35, -80.65)}
URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
NAME = "med ?spa|medical spa|aesthetic|botox|laser|skin|cosmetic"
ICP = re.compile(NAME, re.I)
UA = "kodoai-osm-probe/0.1 (one-off research probe)"


def query(b):
    bb = ",".join(map(str, b))
    sel = [f'nwr["shop"="beauty"]({bb});', f'nwr["beauty"]({bb});', f'nwr["healthcare"]({bb});',
           f'nwr["amenity"~"^(clinic|doctors)$"]({bb});', f'nwr["leisure"="spa"]({bb});', f'nwr["amenity"="spa"]({bb});',
           f'nwr["name"~"{NAME}",i]({bb});']
    return f"[out:json][timeout:90];({''.join(sel)});out tags center;"


def fetch(q):
    for attempt in range(2):
        for u in URLS:
            try:
                req = urllib.request.Request(u, urllib.parse.urlencode({"data": q}).encode(), {"User-Agent": UA})
                return json.load(urllib.request.urlopen(req, timeout=90))["elements"]
            except Exception as e:  # 429/504: wait and move on / retry once
                print("  retry", u, e, file=sys.stderr); time.sleep(15)
    return []


def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def lead(t):
    w = t.get("website") or t.get("contact:website") or t.get("url")
    icp = bool(ICP.search(t.get("name", "") + " " + " ".join(t.values())))
    return {"name": t.get("name"), "website": w, "domain": _domain(w), "state": t.get("addr:state"), "city": t.get("addr:city"),
            "categories": [], "icp": icp}


db = get_db()
tile = db.table("coverage").select("scrape_batch_id").eq("tile", "Manhattan").execute().data[0]["scrape_batch_id"]
ours = db.table("leads").select("name,domain,city,place_id").eq("batch_id", tile).execute().data
all_dom = {r["domain"] for r in fetch_all(lambda: db.table("leads").select("domain").not_.is_("domain", "null").order("id"))}
print("our manhattan leads", len(ours), "all-table domains", len(all_dom))
for area, b in [(a, v) for a, v in AREAS.items() if not sys.argv[1:] or sys.argv[1] in a]:  # optional arg: area substring
    els = fetch(query(b)); time.sleep(8)
    ts = [e.get("tags", {}) for e in els]
    L = [lead(t) for t in ts]
    has = lambda f: sum(1 for t in ts if f(t))
    r = {"elements": len(els), "named": has(lambda t: t.get("name")),
         "website": has(lambda t: t.get("website") or t.get("contact:website") or t.get("url")),
         "phone": has(lambda t: t.get("phone") or t.get("contact:phone")),
         "addr_city": has(lambda t: t.get("addr:city")), "addr_state": has(lambda t: t.get("addr:state")),
         "addr_postcode": has(lambda t: t.get("addr:postcode")), "opening_hours": has(lambda t: t.get("opening_hours")),
         "on_icp(name|tags)": sum(l["icp"] for l in L), "on_icp_name_only": sum(bool(ICP.search(l["name"] or "")) for l in L),
         "website+icp": sum(1 for l in L if l["icp"] and l["domain"]),
         "clean_keep(cats=[])": sum(1 for l in L if l["name"] and clean_decision(l) is None),
         "clean_keep(icp as 'Medical spa')": sum(1 for l in L if l["icp"] and l["name"] and clean_decision({**l, "categories": ["Medical spa"]}) is None),
         "unusable(no domain)": sum(1 for l in L if not l["domain"]), "unusable(no name)": sum(1 for l in L if not l["name"])}
    if area.startswith("Manhattan"):
        doms = {l["domain"] for l in L if l["domain"]}
        names = [(norm(l["name"]), l) for l in L if l["name"]]
        d = n = 0
        for o in ours:
            if o["domain"] in doms: d += 1
            if any(difflib.SequenceMatcher(None, norm(o["name"]), nm).ratio() >= .85 for nm, _ in names): n += 1
        r.update({"ours_in_osm_by_domain": d, "ours_in_osm_by_fuzzy_name>=.85": n,
                  "osm_icp_with_site_new_to_leads_table": sum(1 for l in L if l["icp"] and l["domain"] and l["domain"] not in all_dom),
                  "osm_any_with_site_new_to_leads_table": sum(1 for l in L if l["domain"] and l["domain"] not in all_dom)})
    print(area, json.dumps(r, indent=1))
