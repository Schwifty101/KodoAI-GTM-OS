"""Recontact pass (Plan 9): a contact the policy releases gets a NEW lead (round + 1), re-verified with Hunter, created in its final
status (`enriched` or `no_buyer`, never `cleaned`: autopilot would run enrich on it). The old lead, its touches and every
suppression row are never edited. Dry run (the default) reads only; Apply needs recontact_on, a limit and Hunter allowance."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from gtm.budget import CAP_KEYS, BudgetExceeded, spent_since
from gtm.buyer import is_decision_maker, is_role_email
from gtm.clean import SCHOOL_WORDS, _is_us
from gtm.costs import spend_context
from gtm.db import fetch_all
from gtm.hunter import OutOfCredits
from gtm.recontact import OPEN_TOUCH_STATUSES, _day, clear_rows, lead_released
from gtm.scrape import _domain
from gtm.settings_store import setting
from gtm.sheet_import import _usable_domain
from gtm.sheet_verify import verify_lead
from gtm.status import Status
from gtm.tz import lead_tz

BUCKET = "hunter_recontact"
CREDIT = 0.5  # one Hunter email verification
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)  # the allowance is lifetime
NOT_LIVE = {Status.SCRAPED.value, Status.REJECTED.value, Status.NO_BUYER.value, Status.SUPPRESSED.value}  # every other status is a live twin
HIST_COLS = "id,email,domain,business_name,owner_name,owner_title,website,city,state,round,outcome,date_basis,first_sent_on,last_sent_on,touches_sent,source,lead_id"
LEAD_COLS = "id,place_id,status,name,website,domain,city,state,owner_name,owner_title,owner_email,round,history_id"


def allowance_left(db) -> float:
    return setting(CAP_KEYS[BUCKET], db) - spent_since(db, BUCKET, EPOCH)


def _world(db, today: date) -> SimpleNamespace:
    """One read of everything the pass looks at. Every read is paged (fetch_all); the ledger goes first, so a missing table fails before anything else."""
    days, cap = setting("recontact_days", db), setting("recontact_max_rounds", db)
    hist = fetch_all(lambda: db.table("contact_history").select(HIST_COLS).order("id"))
    sup = fetch_all(lambda: db.table("suppression").select("email,domain,reason").order("id"))
    leads = fetch_all(lambda: db.table("leads").select(LEAD_COLS).order("id"))  # ponytail: every lead is read; narrow to live and sent leads if the table passes ~50k rows
    touches: dict[str, list[dict]] = {}
    for t in fetch_all(lambda: db.table("touches").select("lead_id,status,sent_at").in_("status", ["sent", *sorted(OPEN_TOUCH_STATUSES)]).order("id")):
        touches.setdefault(t["lead_id"], []).append(t)
    return SimpleNamespace(today=today, days=days, cap=cap, hist=hist, sup=sup, leads=leads, touches=touches)


def _released(w, lead: dict) -> bool:
    return lead_released(lead, w.touches.get(lead["id"], []), w.today, w.days, w.cap)


def _os_row(lead: dict, touches: list[dict]) -> dict:
    """The ledger snapshot of an OS-mailed lead, exactly as it would be inserted (no id yet)."""
    sent = sorted(_day(t["sent_at"]) for t in touches if t["status"] == Status.SENT.value)
    return {"source": "os", "email": (lead["owner_email"] or "").lower() or None, "domain": (lead["domain"] or "").lower() or None, "business_name": lead["name"],
            "owner_name": lead["owner_name"], "owner_title": lead["owner_title"], "website": lead["website"], "city": lead["city"], "state": lead["state"],
            "round": lead.get("round") or 1, "outcome": "no_reply", "date_basis": "exact", "first_sent_on": sent[0].isoformat(), "last_sent_on": sent[-1].isoformat(),
            "touches_sent": min(len(sent), 3), "lead_id": lead["id"]}


def _candidates(w) -> list[dict]:
    """Ledger rows (they carry an id) and snapshot rows of OS leads (no id yet), oldest last send first. An OS lead goes through the same
    clear_rows rule as a ledger row, so a permanent suppression key or an unclear ledger row on a shared key blocks it too."""
    spawned = {l["history_id"] for l in w.leads if l.get("history_id")}
    snapped = {h["lead_id"] for h in w.hist if h.get("source") == "os" and h.get("lead_id")}
    by_id = {l["id"]: l for l in w.leads}
    os_rows = [_os_row(l, w.touches[l["id"]]) for l in w.leads if l["id"] not in snapped and _released(w, l)]
    # an os snapshot whose lead has since replied, bounced or been suppressed is no candidate
    rows = [r for r in clear_rows(w.sup, w.hist + os_rows, w.today, w.days, w.cap)
            if r.get("id") not in spawned and (r.get("lead_id") not in by_id or _released(w, by_id[r["lead_id"]]))]
    return sorted(rows, key=lambda r: (_day(r["last_sent_on"]), str(r.get("id") or r["lead_id"])))


def candidates(db, today: date) -> list[dict]:
    return _candidates(_world(db, today))


def _live(w) -> tuple[set[str], set[str]]:
    """Domains and emails of live leads. A previous round of the same contact is released (old, no reply), so it is not live."""
    live = [l for l in w.leads if l["status"] not in NOT_LIVE and not _released(w, l)]
    return {(l["domain"] or "").lower() for l in live} - {""}, {(l["owner_email"] or "").lower() for l in live} - {""}


def _domain_of(c: dict) -> str | None:
    return _usable_domain((c.get("domain") or "").strip().lower() or None) or _usable_domain(_domain(c.get("website")))


def _skip(c: dict, domain: str | None, email: str, live: tuple[set[str], set[str]]) -> str | None:
    """Why a candidate is not worth a credit, or None. All free local checks."""
    name = c.get("business_name") or ""
    if not ((c.get("owner_name") or "").strip() and is_decision_maker(c.get("owner_title"))):
        return "not_decision_maker"
    if not email:
        return "no_email"
    if not domain:
        return "no_domain"
    if not _is_us(c.get("state")):
        return "not_us"
    if "day spa" in name.lower():
        return "day_spa"
    if SCHOOL_WORDS.search(name):
        return "school"
    return "live_twin" if domain in live[0] or email in live[1] else None


def _batch(db, today: date) -> str:
    name = f"Recontact {today}"  # one batch per day, as the sheet import does
    have = db.table("batches").select("id").eq("name", name).limit(1).execute().data
    return have[0]["id"] if have else db.table("batches").insert({"name": name}).execute().data[0]["id"]


def run_recontact(db, pool, limit: int | None, confirm: bool, today: date) -> dict[str, int]:
    if confirm:
        if setting("recontact_on", db) is not True:
            raise ValueError("recontact_on is off: nothing done")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("--limit N (a positive number) is required with --confirm")
        if allowance_left(db) < CREDIT:
            raise BudgetExceeded(f"{BUCKET}: lifetime allowance used up or not set ({CAP_KEYS[BUCKET]})", "credit")  # before any paid call or write
    w = _world(db, today)
    todo = _candidates(w)
    live = _live(w)
    counts: dict[str, int] = {"candidates": len(todo)}
    eligible = made = 0
    batch_id = None
    for i, c in enumerate(todo):
        if confirm and made >= limit:  # the limit counts created leads, not skips, so skipped candidates never clog the front of the queue
            break
        domain, email = _domain_of(c), (c.get("email") or "").strip().lower()
        reason = _skip(c, domain, email, live)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            continue
        eligible += 1
        if not confirm:
            continue
        batch_id = batch_id or _batch(db, today)
        try:
            with spend_context(batch_id=batch_id):
                verified = verify_lead(pool, c, email, BUCKET)
        except (OutOfCredits, BudgetExceeded):
            counts["out_of_credits"] = len(todo) - i  # this candidate and everything after it stay untouched
            break
        hid = c.get("id") or db.table("contact_history").insert(c).execute().data[0]["id"]  # an OS lead gets its snapshot first, then its new lead
        status = Status.ENRICHED.value if verified else Status.NO_BUYER.value
        db.table("leads").insert({
            "place_id": f"recontact:{hid}", "name": c.get("business_name") or domain, "website": c.get("website") or None, "domain": domain,
            "city": c.get("city"), "state": c.get("state"), "tz": lead_tz(c.get("state"), c.get("city")), "owner_name": c["owner_name"].strip(),
            "owner_title": c["owner_title"], "owner_email": None if not verified and is_role_email(email) else email, "email_source": "history",
            "email_verified": verified, "status": status, "round": (c.get("round") or 1) + 1, "history_id": hid, "batch_id": batch_id}).execute()
        if status not in NOT_LIVE:
            live[0].add(domain)
            live[1].add(email)
        made += 1
        counts[status] = counts.get(status, 0) + 1
    if confirm:
        print(f"recontact: {counts}")
        return counts
    n = eligible if limit is None else min(eligible, limit)
    counts["eligible"] = eligible
    print(f"recontact dry run: {counts}")
    print(f"would verify {n}: 0.5 x {n} = {CREDIT * n} Hunter credits; allowance left {allowance_left(db)}")
    print("dry run: nothing written (use --confirm)")
    return counts
