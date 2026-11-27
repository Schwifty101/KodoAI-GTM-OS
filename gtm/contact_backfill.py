"""Backfill `contact_history` (Plan 9) from the Notion tracker export and the sheet's green rows.

Everything before `run_backfill` is pure or read-only; `run_backfill` is the only writer, writes only `contact_history`, only with
confirm, and never touches `suppression`. Ledger keys are derived exactly as `gtm.import_history` derived the suppression keys
(lowercase email, `scrape._domain` of the website) so a ledger row can lift the suppression rows it came from. Webmail and
booking-platform domains are never a ledger domain (`sheet_import._usable_domain`, a superset of the import_history rule: it also drops
booking-suffix domains; such a contact's domain row stays in suppression, so it stays blocked, which is fail closed).
Reports carry counts and fixed reason words only: no addresses, names or company names.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta

from gtm.db import fetch_all
from gtm.recontact import CLEAR_OUTCOMES, last_sent_bound, notion_outcome
from gtm.scrape import _domain
from gtm.settings_store import setting
from gtm.sheet import read_tab
from gtm.sheet_import import _usable_domain, lead_fields, place_key
from gtm.sheet_map import TAB_STATE, MappedRow, map_tab

TABLE = "contact_history"
SHEET_FLOOR = date(2026, 11, 18)  # the sheet import day: a sheet-sent placeholder date is never earlier (owner answer 2026-11-26)
STRICTNESS = ("do_not_contact", "bounce", "opt_out", "negative", "disqualified", "booked", "client", "replied", "unknown", "auto_reply", "no_reply")
# unknown is stricter than the clear outcomes because it blocks; the clear ones come last
FIELDS = {"founder": "founder", "role": "role", "company": "company", "email": "email", "website": "website", "state": "state",
          "hq city": "hq_city", "status": "status", "reply type": "reply_type", "touch": "touch", "initial sent": "initial_sent",
          "last contacted": "last_contacted", "do not contact": "do_not_contact", "subject": "subject", "vector used": "vector_used",
          "campaign batch": "campaign_batch"}  # the Email Body column is deliberately not here: read by nobody, stored nowhere
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
ISO_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
LONG_DAY = re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})\b")
YES = {"yes", "true", "checked", "__yes__", "1"}
NO_REPLY_TEXT = {"", "none", "n/a", "-"}


def _date(text: str) -> date | None:
    """Every date in the cell, the latest wins: a later date only ever delays a contact's return (a Notion range gives its end)."""
    found = [(int(y), int(m), int(d)) for y, m, d in ISO_DAY.findall(text)]
    found += [(int(y), MONTHS[mon[:3].lower()], int(d)) for mon, d, y in LONG_DAY.findall(text) if mon[:3].lower() in MONTHS]
    days = []
    for y, m, d in found:
        try:
            days.append(date(y, m, d))
        except ValueError:
            pass
    return max(days) if days else None


def parse_notion_csv(text: str) -> list[dict]:
    """Notion CSV export -> one dict per row. Tolerates a BOM, absent or extra columns and blank lines."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    col = {FIELDS[h.strip().lower()]: i for i, h in enumerate(next(reader, [])) if h.strip().lower() in FIELDS}
    out = []
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        get = lambda k: cells[col[k]].strip() if k in col and col[k] < len(cells) else ""  # noqa: E731
        email, reply, touch = get("email").lower(), get("reply_type"), re.search(r"\d+", get("touch"))
        out.append({"founder": get("founder"), "role": get("role"), "company": get("company"), "email": email if "@" in email else "",
                    "website": get("website"), "state": get("state"), "hq_city": get("hq_city"), "status": get("status"),
                    "reply_type": "" if reply.lower() in NO_REPLY_TEXT else reply, "touch": int(touch.group()) if touch else None,
                    "initial_sent": _date(get("initial_sent")), "last_contacted": _date(get("last_contacted")),
                    "do_not_contact": get("do_not_contact").lower() in YES, "subject": get("subject"), "vector_used": get("vector_used"),
                    "campaign_batch": get("campaign_batch")})
    return out


def _ledger(**f) -> dict:
    """One shape for every ledger row, so a bulk insert never meets differing keys."""
    return {"email": None, "domain": None, "business_name": None, "owner_name": None, "owner_title": None, "website": None, "city": None,
            "state": None, "subject": None, "vector": None, "round": 1, "first_sent_on": None, "last_sent_on": None, "date_basis": "upper_bound",
            "touches_sent": None, "outcome": "unknown", "source": None, "source_ref": None, **f}


def _join(a: dict, b: dict) -> dict:
    """Two rows of one contact: the later date (and its basis) leads, empty fields are filled from the other, the strictest outcome wins."""
    new, old = sorted((a, b), key=lambda r: (r["last_sent_on"], r["date_basis"] == "exact"))[::-1]
    row = {k: v if v is not None else old[k] for k, v in new.items()}
    firsts, touches = [r["first_sent_on"] for r in (a, b) if r["first_sent_on"]], [r["touches_sent"] for r in (a, b) if r["touches_sent"] is not None]
    row["first_sent_on"], row["touches_sent"] = min(firsts, default=None), max(touches, default=None)
    row["outcome"] = min(a["outcome"], b["outcome"], key=STRICTNESS.index)
    return row


def _merge(rows: list[dict]) -> list[dict]:
    """One row per contact: its email, or for a row with no email its domain (different people on one domain stay separate)."""
    out: dict[tuple, dict] = {}
    for r in rows:
        k = ("e", r["email"]) if r["email"] else ("d", r["domain"])
        out[k] = _join(out[k], r) if k in out else r
    return list(out.values())


def notion_ledger_rows(records: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """Ledger rows and the skipped rows with a reason. A skipped row has no ledger row, so its suppression rows keep blocking it."""
    rows, skipped = [], []
    for n, r in enumerate(records, start=1):
        label = f"{r['campaign_batch'] or 'notion'}:row{n}"
        initial, email, domain = r["initial_sent"], r["email"] or None, _usable_domain(_domain(r["website"]))
        if initial is None:
            skipped.append((label, "no_send_date"))
        elif not email and not domain:
            skipped.append((label, "no_key"))
        else:
            last = last_sent_bound(initial, r["last_contacted"])
            rows.append(_ledger(
                email=email, domain=domain, business_name=r["company"] or None, owner_name=r["founder"] or None, owner_title=r["role"] or None,
                website=r["website"] or None, city=r["hq_city"] or None, state=r["state"] or None, subject=r["subject"] or None,
                vector=r["vector_used"] or None, first_sent_on=initial, last_sent_on=last,
                date_basis="exact" if r["last_contacted"] is not None and r["last_contacted"] >= initial + timedelta(days=7) else "upper_bound",
                touches_sent=None if r["touch"] is None else max(0, min(3, r["touch"])),
                outcome=notion_outcome(r["status"], r["reply_type"], r["do_not_contact"]), source="notion", source_ref=r["campaign_batch"] or None))
    return _merge(rows), skipped


def sheet_ledger_rows(rows: list[MappedRow], sheet_sent: dict[tuple, date | None], known: set[str],
                      skipped: list[tuple[str, str]] | None = None) -> list[dict]:
    """Ledger rows for the sheet rows the owner marked green when they were imported.

    `sheet_sent` is `load_sheet_sent`: exactly the green-at-import rows, (tab, block, row_key) -> the date of their sheet-sent
    suppression row (None when that row is missing). Live colours are never read: the OS paints colours too. `known` is every key
    already in the Notion ledger rows: that row has the real date. Reasons go to `skipped` when given."""
    out = []
    for r in rows:
        try:
            k = (r.tab, r.block, place_key(r))
        except ValueError:
            continue  # never tracked, so never in sheet_sent
        if k not in sheet_sent:
            continue
        label = f"{r.tab}:{r.row_no}"
        lf = lead_fields(r)
        email, domain = (r.emails[0] if r.emails else None), _usable_domain(lf["domain"])
        if not email and not domain:
            reason = "no_key"
        elif known & {x for x in (*r.emails, domain) if x}:
            reason = "known"
        elif sheet_sent[k] is None:
            reason = "no_date"
        else:
            out.append(_ledger(email=email, domain=domain, business_name=lf["name"], owner_name=lf["owner_name"], owner_title=lf["owner_title"],
                               website=lf["website"], city=r.fields.get("city") or None, state=r.fields.get("state") or None,
                               last_sent_on=max(sheet_sent[k], SHEET_FLOOR), outcome="no_reply", source="sheet", source_ref=r.tab))
            continue
        if skipped is not None:
            skipped.append((label, reason))
    return _merge(out)


def load_sheet_sent(db) -> dict[tuple, date | None]:
    """(tab, block, row_key) of every row imported green -> the day its sheet-sent suppression row was created (None: no such row)."""
    green = fetch_all(lambda: db.table("sheet_rows").select("tab,block,row_key,suppression_id").eq("colour_seen", "green").order("id"))
    sup = {s["id"]: s for s in fetch_all(lambda: db.table("suppression").select("id,reason,created_at").order("id"))}
    out: dict[tuple, date | None] = {}
    for g in green:
        s = sup.get(g["suppression_id"])
        out[(g["tab"], g["block"], g["row_key"])] = date.fromisoformat(s["created_at"][:10]) if s and s["reason"] == "sheet-sent" and s["created_at"] else None
    return out


def plan_backfill(db, csv_text: str, sheet_id: str | None = None, svc=None) -> tuple[list[dict], list[tuple[str, str]]]:
    """The whole plan, read only. The sheet tabs are read (and the database touched) only when sheet_id is given."""
    rows, skipped = notion_ledger_rows(parse_notion_csv(csv_text))
    if sheet_id:
        if svc is None:
            from gtm.sheet import sheets_service
            svc = sheets_service()
        mapped = [r for tab in TAB_STATE for r in map_tab(tab, read_tab(svc, sheet_id, tab))]
        rows += sheet_ledger_rows(mapped, load_sheet_sent(db), {k for r in rows for k in (r["email"], r["domain"]) if k}, skipped)
    return rows, skipped


def _table_missing(e: Exception) -> bool:
    return getattr(e, "code", None) in ("PGRST205", "42P01")  # PostgREST: table not in the schema cache; Postgres: undefined table


def _key(r: dict) -> tuple:
    return (r["source"], r.get("email") or "", r.get("domain") or "", r["round"])  # the unique index, an expression index: no on_conflict


def run_backfill(db, rows: list[dict], confirm: bool, today: date | None = None, skipped: list[tuple[str, str]] | None = None) -> dict[str, int]:
    """Insert the rows not already in `contact_history` (200 per request), only with confirm. Counts only, no personal data."""
    today = today or date.today()
    try:
        have = {_key(r) for r in fetch_all(lambda: db.table(TABLE).select("source,email,domain,round").order("id"))}
        missing = False
    except Exception as e:
        if not _table_missing(e):
            raise
        if confirm:
            raise RuntimeError("contact_history does not exist: apply migration 0018 first") from e
        have, missing = set(), True
    new, seen = [], set(have)
    for r in rows:
        if _key(r) not in seen:
            seen.add(_key(r))
            new.append(r)
    try:
        days = int(setting("recontact_days", db))
    except Exception:
        days = 60
    days = days if days >= 1 else 60
    counts: dict[str, int] = {"rows": len(rows), "new": len(new), "existing": len(rows) - len(new), "inserted": 0, "eligible_now": 0}
    if missing:
        counts["ledger_table_missing"] = 1

    def bump(k: str) -> None:
        counts[k] = counts.get(k, 0) + 1

    for r in rows:
        bump(f"outcome:{r['outcome']}")
        if r["outcome"] in CLEAR_OUTCOMES:  # only these ever come back: no week for a bounce
            first = r["last_sent_on"] + timedelta(days=days)
            bump(f"week:{first - timedelta(days=first.weekday())}")
            counts["eligible_now"] += first <= today
    for _, reason in skipped or []:
        bump(f"skipped:{reason}")
    if confirm:
        for i in range(0, len(new), 200):
            chunk = [{k: v.isoformat() if isinstance(v, (date, datetime)) else v for k, v in r.items()} for r in new[i:i + 200]]
            db.table(TABLE).insert(chunk).execute()
            counts["inserted"] += len(chunk)
    return counts
