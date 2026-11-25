"""Manual queue: pick named-but-no-email leads, put them on the Queue tab, read ContactOut pastes back."""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote_plus

from gtm.budget import BudgetExceeded
from gtm.clean import run_clean
from gtm.costs import spend_context
from gtm.db import fetch_all
from gtm.select import _blocklists, blocked_reason
from gtm.hunter import OutOfCredits
from gtm.sheet import QUEUE_TAB, read_tab, write_queue_tab
from gtm.sheet_import import BATCH_NAME, _agent
from gtm.sheet_verify import verify_lead
from gtm.status import Status

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


def pull_sheet_only(db, svc, sheet_id: str) -> int:
    """Uncoloured named rows without an email that have no lead yet: insert scraped, clean, set no_buyer, track in sheet_rows.
    Free: never runs the paid enrich finders. Returns how many became no_buyer."""
    from gtm.scrape import _domain
    from gtm.tz import lead_tz

    cands = [(m, k) for m, k in _mapped(svc, sheet_id) if m.colour is None and not m.emails and (m.fields.get("owner_name") or "").strip() and not _agent(m.fields)]
    keys = [k for _, k in cands]
    have = _in(db, "leads", "id,place_id,status,batch_id", "place_id", keys)
    sheet_batches = {b["id"] for b in db.table("batches").select("id").like("name", f"{BATCH_NAME}%").execute().data}
    # a lead of ours still scraped or cleaned (an earlier run died midway, with or without its sheet_rows row) is retried, not "known"
    retry = {r["place_id"] for r in have if r["batch_id"] in sheet_batches and r["status"] in ("scraped", "cleaned")}
    known = {r["place_id"] for r in have} - retry
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
    for b in {batch_id} | {r["batch_id"] for r in have if r["place_id"] in retry}:
        run_clean(db, b, strict=False)
    by_key = {k: m for m, k in fresh}
    n = 0
    # rejected leads get no sheet_rows entry and so stay hidden from later pulls (accepted)
    for r in _in(db, "leads", "id,place_id,status", "place_id", list(by_key)):
        if r["status"] != Status.CLEANED.value:
            continue
        m = by_key[r["place_id"]]
        # tracking row first: if it fails the lead is still cleaned and the next pull retries it
        db.table("sheet_rows").upsert({"tab": m.tab, "block": m.block, "row_key": r["place_id"], "lead_id": r["id"], "sheet_row_no": m.row_no,
                                       "colour_seen": "none"}, on_conflict="tab,block,row_key").execute()
        db.table("leads").update({"status": Status.NO_BUYER.value}).eq("id", r["id"]).execute()
        n += 1
    return n


def _row(lead: dict) -> list[str]:
    url = "https://www.linkedin.com/search/results/people/?keywords=" + quote_plus(f"{lead['owner_name']} {lead['name']}")
    return [lead["name"], lead["owner_name"], lead.get("domain") or "", url, "", "waiting", lead["id"]]


def _in(db, table: str, cols: str, key: str, ids: list[str]) -> list[dict]:
    return [r for i in range(0, len(ids), 100) for r in db.table(table).select(cols).in_(key, ids[i:i + 100]).execute().data]


def run_queue(db, svc, pool, sheet_id: str, size: int, confirm: bool = False) -> dict[str, int]:
    """Read the Queue tab, verify pasted emails (daily `hunter` bucket), top the tab up to `size` waiting rows, rewrite it.
    Rows are matched by the lead id in the row. Without `confirm` it prints the plan and writes and spends nothing."""
    try:
        tab = read_tab(svc, sheet_id, QUEUE_TAB)
    except ValueError:  # no Queue tab yet: write_queue_tab creates it
        tab = []
    rows: dict[str, list[str]] = {}
    for r in tab:  # header and junk rows have no lead id; a duplicated id keeps its first row
        c = [*r.cells, *[""] * (7 - len(r.cells))]
        if c[6].strip() and c[6] != "lead_id":
            rows.setdefault(c[6].strip(), c)
    state = {r["lead_id"]: r["queue_state"] for r in _in(db, "sheet_rows", "lead_id,queue_state", "lead_id", list(rows)) if r["queue_state"]}
    ignored = [i for i, c in rows.items() if state.get(i) != "waiting" and c[4].strip()]
    pasted = [i for i, c in rows.items() if state.get(i) == "waiting" and c[4].strip()]
    waiting_ids = [i for i in rows if state.get(i) == "waiting"]
    counts = {"enriched": 0, "failed": 0, "ignored": len(ignored), "out_of_credits": 0, "errors": 0, "added": 0, "waiting": 0}
    if ignored:
        print("ignored (lead not waiting):", ", ".join(ignored))
    if not confirm:
        topup = max(0, size - (len(waiting_ids) - len(pasted)))
        print(f"queue plan: verify {len(pasted)} pasted ({len(pasted) * 0.5} credits), ignore {len(ignored)}, top up {topup} rows to {size}; "
              f"{len(select_queue(db, topup))} candidates now. Dry run: nothing written or spent.")
        return counts
    leads = {r["id"]: r for r in _in(db, "leads", "id,owner_name,owner_title", "id", pasted)}
    for done, i in enumerate(pasted):
        email = rows[i][4].strip().lower()
        try:
            with spend_context(lead_id=i):
                # a malformed paste fails with no spend; queue spend is the daily bucket, not the import allowance
                ok = bool(re.fullmatch(r"\S+@\S+\.\S+", email)) and verify_lead(pool, leads[i], email, "hunter")
        except (OutOfCredits, BudgetExceeded):
            counts["out_of_credits"] = len(pasted) - done  # the rows stay waiting, typed emails kept
            break
        except RuntimeError:  # one Hunter failure (non-200/202): this row stays waiting, the rest go on
            counts["errors"] += 1
            continue
        if ok:
            db.table("leads").update({"status": Status.ENRICHED.value, "email_verified": True, "owner_email": email, "email_source": "contactout"}).eq("id", i).execute()
        # a failed paste is not stored; the lead stays no_buyer and is never re-queued
        db.table("sheet_rows").update({"queue_state": "verified" if ok else "failed"}).eq("lead_id", i).execute()
        waiting_ids.remove(i)
        counts["enriched" if ok else "failed"] += 1
    # the database is the truth for who is waiting: a waiting lead missing from the tab (a failed earlier write) is put back
    db_waiting = [r["lead_id"] for r in fetch_all(lambda: db.table("sheet_rows").select("lead_id").eq("queue_state", "waiting").order("id")) if r["lead_id"]]
    out = [rows[i] if i in rows else None for i in db_waiting]
    missing = [i for i, o in zip(db_waiting, out) if o is None]
    back = {r["id"]: _row(r) for r in _in(db, "leads", "id,name,owner_name,domain", "id", missing)}
    out = [[*o[:5], "waiting", o[6]] if o else back[i] for i, o in zip(db_waiting, out) if o or i in back]
    new = select_queue(db, max(0, size - len(out)))
    if len(new) < size - len(out):  # short of candidates: pull named sheet-only rows in (free), then look again
        pull_sheet_only(db, svc, sheet_id)
        new = select_queue(db, size - len(out))
    for lead in new:
        if db.table("sheet_rows").select("id").eq("lead_id", lead["id"]).execute().data:
            db.table("sheet_rows").update({"queue_state": "waiting"}).eq("lead_id", lead["id"]).execute()
        else:
            db.table("sheet_rows").insert({"tab": QUEUE_TAB, "block": 0, "row_key": lead["id"], "lead_id": lead["id"], "queue_state": "waiting"}).execute()
        out.append(_row(lead))
    write_queue_tab(svc, sheet_id, out)
    counts["added"], counts["waiting"] = len(new), len(out)
    return counts
