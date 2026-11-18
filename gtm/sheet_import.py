"""Import the owner's Google Sheet: green/red rows -> suppression, uncoloured rows with an email -> scraped leads.

`plan_import` is pure; `run_import_sheet` is the only writer and writes only with confirm."""
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from gtm.clean import PLATFORM_DOMAINS, PLATFORM_SUFFIXES
from gtm.db import fetch_all
from gtm.replies import FREE_MAIL
from gtm.scrape import _domain
from gtm.sheet import read_tab
from gtm.sheet_map import TAB_STATE, MappedRow, map_tab
from gtm.tz import lead_tz

BATCH_NAME = "Sheet import"
REASON = {"green": "sheet-sent", "red": "sheet-dropped"}
PLACE_ID = re.compile(r"place_id[:=](ChIJ[\w-]+)|\b(ChIJ[\w-]+)")
HASHED = ("name", "website", "owner_name", "owner_title", "owner_linkedin")


@dataclass
class ImportPlan:
    suppress: list[dict] = field(default_factory=list)
    leads: list[dict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (Tab:row_no, reason); no lead data
    left_for_queue: int = 0
    tracked_new: list[dict] = field(default_factory=list)


def place_key(row: MappedRow) -> str:
    m = PLACE_ID.search(row.fields.get("maps_url", ""))
    if m:
        return m.group(1) or m.group(2)
    d = _domain(row.fields.get("website"))
    if d:
        return f"domain:{d}"
    raise ValueError(f"{row.tab}:{row.row_no} has no maps url and no website")


def content_hash(row: MappedRow) -> str:
    return hashlib.sha1(json.dumps([[row.fields.get(k, "") for k in HASHED], row.emails]).encode()).hexdigest()


def _usable_domain(d: str | None) -> str | None:
    """Webmail and booking-platform domains would block every business using them: never a suppression domain."""
    if not d or d in FREE_MAIL or any(p in d for p in PLATFORM_DOMAINS) or d.endswith(PLATFORM_SUFFIXES):
        return None
    return d


def _agent(f: dict) -> bool:
    t = f"{f.get('owner_name') or ''} {f.get('owner_title') or ''}".lower()
    return "registered agent" in t or "service of process" in t


def lead_fields(row: MappedRow) -> dict:
    """The sheet-owned fields of a lead; a registered-agent buyer is no owner."""
    f, ag = row.fields, _agent(row.fields)
    return {"name": f.get("name"), "website": f.get("website") or None, "domain": _domain(f.get("website")),
            "owner_name": None if ag else f.get("owner_name") or None, "owner_title": None if ag else f.get("owner_title") or None,
            "owner_linkedin": f.get("owner_linkedin") or None, "owner_email": row.emails[0] if row.emails else None}


def suppress_rows(row: MappedRow, have_emails: set[str], have_domains: set[str]) -> list[dict]:
    reason, out = REASON[row.colour], []
    for e in row.emails:
        if e not in have_emails:
            out.append({"email": e, "reason": reason})
    d = _usable_domain(_domain(row.fields.get("website")))
    if d and d not in have_domains:
        out.append({"domain": d, "reason": reason})
    return out


def plan_import(rows: list[MappedRow], have_emails: set[str], have_domains: set[str], have_place_ids: set[str],
                tracked: dict[tuple[str, int, str], dict], sup_emails: set[str] | None = None,
                sup_domains: set[str] | None = None) -> ImportPlan:
    """have_* = everything known (leads and suppression), used to dedupe leads; sup_* = the suppression table only,
    used to dedupe suppression rows (a coloured row matching an existing lead must still suppress). Default: same as have_*."""
    p, emails, domains, places = ImportPlan(), set(have_emails), set(have_domains), set(have_place_ids)
    s_emails = set(have_emails if sup_emails is None else sup_emails)
    s_domains = set(have_domains if sup_domains is None else sup_domains)
    keys: set = set()
    for r in rows:
        label = f"{r.tab}:{r.row_no}"
        try:
            key = place_key(r)
        except ValueError:
            key = None
        if key and (r.tab, r.block, key) in tracked:
            p.skipped.append((label, "tracked"))
            continue
        track = {"tab": r.tab, "block": r.block, "row_key": key, "sheet_row_no": r.row_no,
                 "content_hash": content_hash(r), "colour_seen": r.colour or "none", "place_id": None, "match": None}
        if r.colour:
            d = _usable_domain(_domain(r.fields.get("website")))
            if not r.emails and not d:
                p.skipped.append((label, "nothing_to_match"))
                continue
            new = suppress_rows(r, s_emails, s_domains)
            p.suppress += new
            s_emails |= {x["email"] for x in new if "email" in x}
            s_domains |= {x["domain"] for x in new if "domain" in x}
            emails |= {x["email"] for x in new if "email" in x}
            domains |= {x["domain"] for x in new if "domain" in x}
            track["match"] = ("email", r.emails[0].lower()) if r.emails else ("domain", d)
        elif not r.emails:
            if r.fields.get("owner_name") and not _agent(r.fields):
                p.left_for_queue += 1
            continue
        else:
            lf = lead_fields(r)
            if not key:
                p.skipped.append((label, "no_key"))
                continue
            if key in places or r.emails[0] in emails or (lf["domain"] and lf["domain"] in domains):
                p.skipped.append((label, "known"))
                if key in places and (r.tab, r.block, key) not in keys:
                    track["place_id"] = key  # known lead with no sheet_rows entry (half-failed run): track it, lead_id resolved at write time
                    keys.add((r.tab, r.block, key))
                    p.tracked_new.append(track)
                continue
            cat = r.fields.get("category") or None
            # ponytail: only the first address of a multi-email cell is kept; the rest are dropped
            p.leads.append({"place_id": key, **lf, "category": cat, "categories": [cat] if cat else [],
                            "city": r.fields.get("city") or None, "state": r.fields.get("state") or None,
                            "tz": lead_tz(r.fields.get("state"), r.fields.get("city")),
                            "email_source": "sheet", "email_verified": False, "status": "scraped"})
            places.add(key)
            emails.add(r.emails[0])
            if lf["domain"]:
                domains.add(lf["domain"])
            track["place_id"] = key
        if key and (r.tab, r.block, key) not in keys:
            keys.add((r.tab, r.block, key))
            p.tracked_new.append(track)
    return p


FROZEN = {"drafted", "sent", "replied", "booked", "bounced", "suppressed", "unsubscribed"}


@dataclass
class SyncPlan:
    updates: list[tuple[str, dict]] = field(default_factory=list)  # (lead_id, patch)
    reverify: list[str] = field(default_factory=list)
    frozen: list[tuple[str, dict]] = field(default_factory=list)  # (lead_id, the sheet's differing values); only when non-empty
    orphaned: list[tuple[str, int, str]] = field(default_factory=list)  # (tab, block, row_key)
    new_suppress: list[dict] = field(default_factory=list)  # not yet filtered against known suppression
    touched: list[tuple[tuple[str, int, str], dict]] = field(default_factory=list)  # sheet_rows patches by key
    finder_email_kept: int = 0  # sheet email differs but the lead's email came from an OS finder: kept


def plan_sync(rows: list[MappedRow], tracked: dict, leads_by_id: dict[str, dict]) -> SyncPlan:
    """One way, sheet -> OS, for rows already tracked. Rows are matched by key; never deletes; a blank sheet cell never wipes a value."""
    s, seen = SyncPlan(), set()
    for r in rows:
        try:
            k = (r.tab, r.block, place_key(r))
        except ValueError:
            continue
        t = tracked.get(k)
        if not t:
            continue
        seen.add(k)
        patch = {"colour_seen": r.colour or "none", "orphaned": False}
        if r.colour and t.get("colour_seen") != r.colour and t.get("colour_written") != r.colour:
            s.new_suppress += [x for x in suppress_rows(r, set(), set()) if x not in s.new_suppress]
        h = content_hash(r)
        lead = leads_by_id.get(t.get("lead_id"))
        if h != t.get("content_hash") and lead:
            want = {k_: v for k_, v in lead_fields(r).items() if v and str(v).strip()}
            if want.get("owner_email") and lead.get("owner_email") and lead.get("email_source") != "sheet":
                # ponytail: a sheet email edit on a lead whose email an OS finder found is ignored; add a per-lead override if it matters
                if want["owner_email"] != lead["owner_email"].lower():
                    s.finder_email_kept += 1
                del want["owner_email"]
            diff = {k_: v for k_, v in want.items() if (str(lead.get(k_) or "").lower() if k_ == "owner_email" else lead.get(k_)) != v}
            if lead["status"] in FROZEN:
                if diff:
                    s.frozen.append((t["lead_id"], diff))  # hash stays old: the difference is reported every run
            else:
                if "owner_email" in diff:
                    diff |= {"email_source": "sheet", "email_verified": False}
                    if lead["status"] not in ("scraped", "rejected"):
                        diff["status"] = "cleaned"
                    s.reverify.append(t["lead_id"])
                if diff:
                    s.updates.append((t["lead_id"], diff))
                patch["content_hash"] = h
        elif h != t.get("content_hash"):
            patch["content_hash"] = h
        if t.get("sheet_row_no") != r.row_no:
            patch["sheet_row_no"] = r.row_no
        s.touched.append((k, patch))
    tabs = {r.tab for r in rows}
    s.orphaned = [k for k, t in tracked.items() if k[0] in tabs and k not in seen and not t.get("orphaned")]
    return s


def _load(db):
    leads = fetch_all(lambda: db.table("leads").select(
        "id,place_id,status,name,website,domain,owner_name,owner_title,owner_linkedin,owner_email,email_source").order("id"))
    sup = fetch_all(lambda: db.table("suppression").select("id,email,domain").order("id"))
    tracked = {(t["tab"], t["block"], t["row_key"]): t for t in fetch_all(lambda: db.table("sheet_rows").select("*").order("id"))}
    return leads, sup, tracked


def _report(tab: str, rows: list[MappedRow], p: ImportPlan, n_sup: int, n_leads: int) -> None:
    c = Counter(r.colour or "none" for r in rows)
    why = dict(Counter(reason for _, reason in p.skipped))
    print(f"{tab}: green {c['green']}, red {c['red']}, uncoloured {c['none']}; suppression rows {n_sup}, leads {n_leads}, "
          f"skipped {why or 0}, left for queue {p.left_for_queue}")


def run_import_sheet(db, svc, sheet_id: str, confirm: bool = False, tab: str | None = None) -> ImportPlan:
    if tab is not None and tab not in TAB_STATE:
        raise ValueError(f"unknown tab {tab!r}; known: {', '.join(TAB_STATE)}")
    mapped = {t: map_tab(t, read_tab(svc, sheet_id, t)) for t in TAB_STATE if tab in (None, t)}  # any missing tab raises before a write
    leads, sup, tracked = _load(db)
    sup_emails = {x["email"].lower() for x in sup if x["email"]}
    sup_domains = {x["domain"] for x in sup if x["domain"]}
    emails = {x["owner_email"].lower() for x in leads if x["owner_email"]} | sup_emails
    domains = {x["domain"] for x in leads if x["domain"]} | sup_domains
    places = {x["place_id"] for x in leads}
    total = ImportPlan()
    for tab, rows in mapped.items():
        p = plan_import(rows, emails, domains, places, tracked, sup_emails, sup_domains)
        _report(tab, rows, p, len(p.suppress), len(p.leads))
        sup_emails |= {x["email"] for x in p.suppress if "email" in x}
        sup_domains |= {x["domain"] for x in p.suppress if "domain" in x}
        emails |= {x["email"] for x in p.suppress if "email" in x} | {x["owner_email"] for x in p.leads if x["owner_email"]}
        domains |= {x["domain"] for x in p.suppress if "domain" in x} | {x["domain"] for x in p.leads if x["domain"]}
        places |= {x["place_id"] for x in p.leads}
        total.suppress += p.suppress
        total.leads += p.leads
        total.skipped += p.skipped
        total.left_for_queue += p.left_for_queue
        total.tracked_new += p.tracked_new
    sync = plan_sync([r for rows in mapped.values() for r in rows], tracked, {x["id"]: x for x in leads})
    sync.new_suppress = [x for x in sync.new_suppress if x.get("email", x.get("domain")) not in (sup_emails if "email" in x else sup_domains)]
    total.suppress += sync.new_suppress
    print(f"sync: {len(sync.updates)} lead updates, {len(sync.reverify)} to re-verify, {len(sync.frozen)} frozen "
          f"(drafted or later; sheet differs), {len(sync.orphaned)} orphaned, {len(sync.new_suppress)} new suppression rows, "
          f"{sync.finder_email_kept} finder_email_kept")
    for lid, diff in sync.frozen:
        print(f"  frozen lead {lid[:8]}: sheet differs in {', '.join(sorted(diff))}")
    if not confirm:
        print("dry run: nothing written (use --confirm)")
        return total
    # Inserts first (suppression, leads, new sheet_rows), then the sheet_rows patches: a failed suppression insert must not
    # leave colour_seen updated, or the owner's red/green mark would never be read again.
    sup_id = {("email", x["email"].lower()): x["id"] for x in sup if x["email"]} | {("domain", x["domain"]): x["id"] for x in sup if x["domain"]}
    for i in range(0, len(total.suppress), 200):
        for x in db.table("suppression").insert(total.suppress[i:i + 200]).execute().data:
            sup_id[("email", x["email"].lower()) if x["email"] else ("domain", x["domain"])] = x["id"]
    lead_id = {x["place_id"]: x["id"] for x in leads}
    if total.leads:
        name = f"{BATCH_NAME} {date.today()}"
        have = db.table("batches").select("id").eq("name", name).limit(1).execute().data
        batch = have[0]["id"] if have else db.table("batches").insert({"name": name}).execute().data[0]["id"]
        for i in range(0, len(total.leads), 200):
            res = db.table("leads").insert([{**x, "batch_id": batch} for x in total.leads[i:i + 200]]).execute().data
            lead_id |= {x["place_id"]: x["id"] for x in res}
    now = datetime.now(timezone.utc).isoformat()
    rows = [{"tab": t["tab"], "block": t["block"], "row_key": t["row_key"], "sheet_row_no": t["sheet_row_no"],
             "content_hash": t["content_hash"], "colour_seen": t["colour_seen"], "colour_written": None, "last_seen_at": now,
             "lead_id": lead_id.get(t["place_id"]), "suppression_id": sup_id.get(t["match"]) if t["match"] else None}
            for t in total.tracked_new]
    for i in range(0, len(rows), 200):
        db.table("sheet_rows").insert(rows[i:i + 200]).execute()
    for lid, patch in sync.updates:
        db.table("leads").update(patch).eq("id", lid).execute()
    for (tab, block, key), patch in sync.touched:
        db.table("sheet_rows").update({**patch, "last_seen_at": now}).eq("tab", tab).eq("block", block).eq("row_key", key).execute()
    for tab, block, key in sync.orphaned:
        db.table("sheet_rows").update({"orphaned": True}).eq("tab", tab).eq("block", block).eq("row_key", key).execute()
    return total
