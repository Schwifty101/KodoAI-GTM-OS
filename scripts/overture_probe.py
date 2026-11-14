"""Probe: can Overture Maps places feed med-spa discovery? Read-only on the DB, free (public S3, DuckDB).
Run: uv run --with duckdb python scripts/overture_probe.py   (duckdb is NOT a project dependency)"""
import difflib, json, os, random, re, sys
from collections import Counter
sys.path.insert(0, ".")
import duckdb
from gtm.clean import clean_decision
from gtm.db import get_db
from gtm.scrape import _domain

REL = "2026-10-21.0"  # latest per stac.overturemaps.org/catalog.json on 2026-11-14
AREAS = {"Manhattan": (-74.02, 40.70, -73.91, 40.88), "Houston": (-95.85, 29.45, -95.00, 30.25)}  # xmin,ymin,xmax,ymax
TILES = {"Manhattan": ["Manhattan"], "Houston": ["Houston", "Sugar Land", "The Woodlands"]}
NAME = "med ?spa|medical spa|aesthetic|botox|laser|skin|cosmetic"
ICP = re.compile(NAME, re.I)
CAT = "spa|beauty|aesthetic|dermat|cosmetic|health|medical|clinic|doctor|surgeon"


def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())


con = duckdb.connect()
con.sql("install httpfs; load httpfs; set s3_region='us-west-2'")
SRC = f"read_parquet('s3://overturemaps-us-west-2/release/{REL}/theme=places/type=place/*', hive_partitioning=1)"
db = get_db()
all_dom = {r["domain"] for r in db.table("leads").select("domain").not_.is_("domain", "null").limit(5000).execute().data}


def fetch(b):
    x0, y0, x1, y1 = b
    return con.sql(f"""select id, names.primary name, confidence, websites[1] website, taxonomy.primary cat,
        array_to_string(taxonomy.hierarchy,'>') hier, array_to_string(taxonomy.alternates,',') alts, addresses[1].freeform addr,
        addresses[1].locality city, addresses[1].region state, addresses[1].postcode zip, sources[1].dataset src, sources[1].license lic,
        operating_status status, len(phones)>0 phone from {SRC}
        where bbox.xmin>={x0} and bbox.xmax<={x1} and bbox.ymin>={y0} and bbox.ymax<={y1}
        and (regexp_matches(names.primary,'{NAME}','i') or regexp_matches(coalesce(array_to_string(taxonomy.hierarchy,'>'),'')||coalesce(array_to_string(taxonomy.alternates,','),''),'{CAT}','i'))""").fetchall()


COLS = "id name conf website cat hier alts addr city state zip src lic status phone".split()
for area, b in AREAS.items():
    rows = [dict(zip(COLS, r)) for r in fetch(b)]
    for r in rows:
        r["domain"] = _domain(r["website"])
        r["icp"] = bool(ICP.search(r["name"] or "")) or bool(re.search("med(ical)?_spa|aesthetic|cosmetic|dermat|skin_care", (r["hier"] or "") + (r["alts"] or ""), re.I))
    ids = [t["scrape_batch_id"] for n in TILES[area] for t in db.table("coverage").select("scrape_batch_id").eq("tile", n).execute().data if t["scrape_batch_id"]]
    ours = [o for i in ids for o in db.table("leads").select("name,domain").eq("batch_id", i).execute().data]
    if not ours and area == "Houston":  # tiles were marked done by hand, no scrape_batch_id: use the Houston batch
        ours = db.table("leads").select("name,domain").eq("batch_id", "e11d97b6-41a0-4957-8d3d-6b1728f74d90").execute().data
    strict = [r for r in rows if re.search("medical_spa|med_spa", (r["cat"] or "") + (r["alts"] or "")) or re.search("med ?spa|medical spa", r["name"] or "", re.I)]
    if "--dump" in sys.argv:  # 30 random STRICT rows per area for a manual precision review, written outside the repo
        random.seed(1)
        keep = "id name conf website domain cat alts addr status src".split()
        json.dump([{k: r[k] for k in keep} for r in random.sample(strict, min(30, len(strict)))], open(f"{os.environ['CLAUDE_JOB_DIR']}/tmp/strict_{area}.json", "w"), indent=1, default=str)
    doms = {r["domain"] for r in rows if r["domain"]}
    names = [norm(r["name"]) for r in rows if r["name"]]
    d = sum(1 for o in ours if o["domain"] in doms)
    n = sum(1 for o in ours if any(difflib.SequenceMatcher(None, norm(o["name"]), nm).ratio() >= .85 for nm in names))
    dn = sum(1 for o in ours if o["domain"] in doms or any(difflib.SequenceMatcher(None, norm(o["name"]), nm).ratio() >= .85 for nm in names))
    icp = [r for r in rows if r["icp"]]
    conf = lambda L, lo, hi: sum(1 for r in L if lo <= (r["conf"] or 0) < hi)
    out = {"candidates": len(rows), "named": sum(bool(r["name"]) for r in rows), "website": sum(bool(r["domain"]) for r in rows),
           "phone": sum(bool(r["phone"]) for r in rows), "on_icp": len(icp), "strict_medspa": len(strict), "strict_with_site": sum(bool(r["domain"]) for r in strict),
           "strict_site_new": sum(1 for r in strict if r["domain"] and r["domain"] not in all_dom), "conf_strict(<.5,.5-.8,>=.8)": [conf(strict, 0, .5), conf(strict, .5, .8), conf(strict, .8, 1.01)],
           "ours_in_strict_by_domain": sum(1 for o in ours if o["domain"] in {r["domain"] for r in strict if r["domain"]}), "on_icp_with_site": sum(bool(r["domain"]) for r in icp),
           "clean_keep(cats=[])": sum(1 for r in rows if r["name"] and clean_decision({**r, "categories": []}) is None),
           "closed_flag": sum(1 for r in rows if r["status"] and r["status"] != "open"),
           "conf_icp(<.5,.5-.8,>=.8)": [conf(icp, 0, .5), conf(icp, .5, .8), conf(icp, .8, 1.01)],
           "ours": len(ours), "ours_found_by_domain": d, "ours_found_by_name>=.85": n, "ours_found_either": dn,
           "icp_site_new_to_leads_table": sum(1 for r in icp if r["domain"] and r["domain"] not in all_dom),
           "top_cats_icp": Counter(r["cat"] for r in icp).most_common(8), "src_icp": Counter(r["src"] for r in icp).most_common(5),
           "lic_icp": Counter(r["lic"] for r in icp).most_common(5)}
    print(area, json.dumps(out, indent=1, default=str))
