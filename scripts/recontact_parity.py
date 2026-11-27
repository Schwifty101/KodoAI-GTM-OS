"""Plan 9 parity check. READ-ONLY (selects only) and counts only: no email, name or domain is printed.
Usage: PYTHONPATH=. uv run python scripts/recontact_parity.py

1. gtm.select._blocklists with the flag off must equal the pre-Plan-9 function on the real rows (AssertionError if not).
2. A simulated flag on, never stored: gtm.select._released_blocklists reads the settings and the ledger read-only and shows what
   would be released. Before migration 0018 the ledger table is missing and released = 0.
The reads are not one snapshot: a live autopilot writing between them can fake a mismatch, so rerun once before trusting a failure."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from unittest.mock import patch

from postgrest.exceptions import APIError

from gtm import select as select_mod
from gtm.db import fetch_all, get_db
from gtm.recontact import CLEAR_OUTCOMES, keys as row_keys
from gtm.settings_store import setting

MISSING_TABLE = {"PGRST205", "42P01"}  # PostgREST schema-cache miss, Postgres undefined_table


def legacy(db) -> tuple[set[str], set[str]]:
    """_blocklists as it was before Plan 9, copied verbatim."""
    sup = set()
    for r in fetch_all(lambda: db.table("suppression").select("email,domain").order("id")):
        sup |= {v.lower() for v in (r["email"], r["domain"]) if v}
    sent = [t["lead_id"] for t in fetch_all(lambda: db.table("touches").select("lead_id").eq("status", "sent").order("id"))]
    contacted = set()
    for i in range(0, len(sent), 100):
        for r in db.table("leads").select("owner_email,domain").in_("id", sent[i : i + 100]).execute().data:
            contacted |= {v.lower() for v in (r["owner_email"], r["domain"]) if v}
    return sup, contacted


def is_missing_table(e: Exception) -> bool:
    return isinstance(e, APIError) and e.code in MISSING_TABLE


def released_by_reason(sup: list[dict], released: set[str]) -> dict[str, int]:
    """Released keys per suppression reason. A key shared by several reasons counts once under each; reasons with none are left out."""
    by: dict[str, set[str]] = {}
    for r in sup:
        by.setdefault(r.get("reason") or "(none)", set()).update(row_keys(r.get("email"), r.get("domain")) & released)
    return {reason: len(ks) for reason, ks in by.items() if ks}


def first_eligible_week(last_sent_on, days: int) -> date | None:
    """Monday of the week in which last_sent_on + days falls; None for a missing or unparseable date."""
    try:
        due = date.fromisoformat(str(last_sent_on)[:10]) + timedelta(days=days)
    except ValueError:
        return None
    return due - timedelta(days=due.weekday())


def ledger_summary(hist: list[dict], days: int) -> tuple[Counter, Counter]:
    """(rows by outcome, rows by first-eligible week). Weeks cover clear outcomes only: no other outcome ever becomes eligible."""
    return (Counter(h.get("outcome") for h in hist),
            Counter(first_eligible_week(h.get("last_sent_on"), days) for h in hist if h.get("outcome") in CLEAR_OUTCOMES))


def analyse(db, today: date) -> dict:
    with patch.object(select_mod, "_recontact_on", lambda db: False):  # the stored flag is never consulted for the parity check
        off = select_mod._blocklists(db, today)
    old = legacy(db)
    assert off == old, f"parity broken: flag-off _blocklists differs from legacy ({len(off[0] ^ old[0])} suppressed and {len(off[1] ^ old[1])} contacted keys differ)"
    res = {"real_flag": setting("recontact_on", db) is True, "sup_before": len(old[0]), "contacted_before": len(old[1]), "ledger": True}
    try:
        sup_after, contacted_after = select_mod._released_blocklists(db, today)  # simulated flag on: reads only, stores nothing
    except APIError as e:
        if not is_missing_table(e):
            raise
        return res | {"ledger": False}
    days, hist = setting("recontact_days", db), fetch_all(lambda: db.table("contact_history").select("outcome,last_sent_on").order("id"))
    sup = fetch_all(lambda: db.table("suppression").select("email,domain,reason").order("id"))
    outcomes, weeks = ledger_summary(hist, days)
    return res | {"days": days, "max_rounds": setting("recontact_max_rounds", db), "sup_after": len(sup_after), "contacted_after": len(contacted_after),
                  "released_by_reason": released_by_reason(sup, old[0] - sup_after), "contacted_freed": len(old[1] - contacted_after),
                  "ledger_rows": len(hist), "outcomes": outcomes, "weeks": weeks}


def render(res: dict) -> list[str]:
    out = ["parity: flag-off _blocklists equals the legacy function (OK)",
           f"stored recontact_on: {'on' if res['real_flag'] else 'off'} (never changed here)",
           f"suppression keys now: {res['sup_before']}; contacted keys now (OS leads): {res['contacted_before']}"]
    if not res["ledger"]:
        return out + ["ledger table missing (migration 0018 not applied): released = 0"]
    by_week = sorted(res["weeks"].items(), key=lambda kv: (kv[0] is None, kv[0] or date.min))
    return out + [
        f"simulated flag on (recontact_days {res['days']}, recontact_max_rounds {res['max_rounds']}):",
        f"  suppression keys released: {res['sup_before'] - res['sup_after']} (left: {res['sup_after']}); by suppression reason:",
        *[f"    {reason}: {n}" for reason, n in sorted(res["released_by_reason"].items())],
        f"  contacted keys freed (OS leads): {res['contacted_freed']} (left: {res['contacted_after']})",
        f"ledger rows: {res['ledger_rows']}; by outcome:",
        *[f"    {outcome}: {n}" for outcome, n in sorted(res["outcomes"].items(), key=lambda kv: str(kv[0]))],
        "first eligible week (Monday), clear outcomes only:",
        *[f"    {week.isoformat() if week else 'no date'}: {n}" for week, n in by_week],
    ]


def main() -> None:
    print("\n".join(render(analyse(get_db(), date.today()))))


if __name__ == "__main__":
    main()
