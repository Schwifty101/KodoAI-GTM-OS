"""Manual queue: pick named-but-no-email leads, put them on the Queue tab, read ContactOut pastes back."""

from __future__ import annotations

from datetime import date

from gtm.clean import run_clean
from gtm.db import fetch_all
from gtm.select import _blocklists, blocked_reason
from gtm.sheet import QUEUE_HEADER, QUEUE_TAB, read_tab, write_queue_tab  # noqa: F401  (Task 9 uses these)
from gtm.status import Status

BATCH_NAME = "Sheet import"
_COLS = "id,name,domain,owner_name,owner_title,owner_linkedin,owner_email,review_count,rating,status"


def queue_order(leads: list[dict]) -> list[dict]:
    """Named owner, then LinkedIn present, then review_count desc, then rating desc; nulls last (sheet-only rows have neither)."""
    def key(l: dict):
        rc, rt = l.get("review_count"), l.get("rating")
        return (not (l.get("owner_name") or "").strip(), not l.get("owner_linkedin"), rc is None, -(rc or 0), rt is None, -(rt or 0))
    return sorted(leads, key=key)


def select_queue(db, n: int) -> list[dict]:
    """no_buyer leads with a saved name and no email, not suppressed or contacted, never one already waiting, verified or failed."""
    skip = {r["lead_id"] for r in fetch_all(lambda: db.table("sheet_rows").select("lead_id").in_("queue_state", ["waiting", "verified", "failed"]).order("id"))}
    leads = fetch_all(lambda: db.table("leads").select(_COLS).eq("status", Status.NO_BUYER.value).not_.is_("owner_name", "null").is_("owner_email", "null").order("id"))
    suppressed, contacted = _blocklists(db)
    ok = [l for l in leads if l["owner_name"].strip() and l["id"] not in skip and not blocked_reason(l, suppressed, contacted)]
    return queue_order(ok)[:n]


def _mapped(svc, sheet_id: str) -> list[tuple]:
    """(MappedRow, place key) for every data row of every tab. Lazy imports: sheet_map and sheet_import are built separately."""
    from gtm.sheet_import import place_key
    from gtm.sheet_map import TAB_STATE, map_tab

    out = []
    for tab in TAB_STATE:
        for m in map_tab(tab, read_tab(svc, sheet_id, tab)):
            try:
                out.append((m, place_key(m)))
            except ValueError:  # no maps_url and no website: nothing to key on
                pass
    return out


def _agent(f: dict) -> bool:
    return any(w in f"{f.get('owner_name')} {f.get('owner_title')}".lower() for w in ("registered agent", "service of process"))


def pull_sheet_only(db, svc, sheet_id: str) -> int:
    """Uncoloured named rows without an email that have no lead yet: insert scraped, clean, set no_buyer, track in sheet_rows.
    Free: never runs the paid enrich finders. Returns how many became no_buyer."""
    from gtm.scrape import _domain
    from gtm.tz import lead_tz

    cands = [(m, k) for m, k in _mapped(svc, sheet_id) if m.colour is None and not m.emails and (m.fields.get("owner_name") or "").strip() and not _agent(m.fields)]
    keys = [k for _, k in cands]
    known = {r["place_id"] for i in range(0, len(keys), 100) for r in db.table("leads").select("place_id").in_("place_id", keys[i:i + 100]).execute().data}
    fresh = [(m, k) for m, k in cands if k not in known]
    if not fresh:
        return 0
    name = f"{BATCH_NAME} {date.today()}"
    batch = db.table("batches").select("id").eq("name", name).execute().data
    batch_id = batch[0]["id"] if batch else db.table("batches").insert({"name": name}).execute().data[0]["id"]
    leads = [{"place_id": k, "name": m.fields["name"], "website": m.fields.get("website"), "domain": _domain(m.fields.get("website")),
              "category": m.fields.get("category"), "categories": [m.fields["category"]] if m.fields.get("category") else [],
              "city": m.fields.get("city"), "state": m.fields.get("state"), "owner_name": m.fields["owner_name"].strip(),
              "owner_title": m.fields.get("owner_title") or None, "owner_linkedin": m.fields.get("owner_linkedin") or None,
              "status": Status.SCRAPED.value, "batch_id": batch_id, "tz": lead_tz(m.fields.get("state"), m.fields.get("city"))} for m, k in fresh]
    db.table("leads").upsert(leads, on_conflict="place_id", ignore_duplicates=True).execute()
    run_clean(db, batch_id)
    by_key = {m_k[1]: m_k[0] for m_k in fresh}
    n = 0
    for r in db.table("leads").select("id,place_id").eq("batch_id", batch_id).eq("status", Status.CLEANED.value).in_("place_id", list(by_key)).execute().data:
        m = by_key[r["place_id"]]
        db.table("leads").update({"status": Status.NO_BUYER.value}).eq("id", r["id"]).execute()
        db.table("sheet_rows").insert({"tab": m.tab, "block": m.block, "row_key": r["place_id"], "lead_id": r["id"], "sheet_row_no": m.row_no,
                                       "colour_seen": "none"}).execute()
        n += 1
    return n
