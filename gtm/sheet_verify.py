"""verify-sheet: Hunter-verify the emails imported from the sheet, inside the one-off import allowance."""

from __future__ import annotations

from gtm.budget import BudgetExceeded
from gtm.buyer import is_decision_maker, is_role_email, pick_buyer
from gtm.costs import spend_context
from gtm.hunter import OutOfCredits
from gtm.select import _blocklists, blocked_reason
from gtm.status import Status


def verify_lead(pool, lead: dict, email: str, bucket: str) -> bool:
    """True when `email` passes the buyer rule for this lead's saved name and title. A lead that cannot qualify
    (no named decision-maker, role address) fails without spending a credit. Raises OutOfCredits or BudgetExceeded."""
    if not ((lead.get("owner_name") or "").strip() and is_decision_maker(lead.get("owner_title")) and not is_role_email(email)):
        return False
    first, _, last = lead["owner_name"].strip().partition(" ")  # same split as gtm.enrich for saved names
    v = pool.verify_email(email, bucket)
    return pick_buyer([{**v, "first_name": first, "last_name": last, "position": lead["owner_title"]}]) is not None


def run_verify_sheet(db, pool, batch_id: str, limit: int | None = None, bucket: str = "hunter_import") -> dict[str, int]:
    """pool is always supplied by the caller (the CLI refuses without --confirm)."""
    q = (db.table("leads").select("id,domain,owner_name,owner_title,owner_email").eq("batch_id", batch_id).eq("status", Status.CLEANED.value)
         .eq("email_source", "sheet").eq("email_verified", False).not_.is_("owner_email", "null"))
    rows = (q.limit(limit) if limit else q).execute().data
    counts: dict[str, int] = {}
    suppressed, contacted = _blocklists(db)
    for done, r in enumerate(rows):
        if blocked_reason(r, suppressed, contacted):
            counts["blocked"] = counts.get("blocked", 0) + 1  # suppressed or already contacted: no credit, stays cleaned
            continue
        if not ((r.get("owner_name") or "").strip() and is_decision_maker(r.get("owner_title"))):
            counts["skipped"] = counts.get("skipped", 0) + 1  # no named owner or not a decision-maker: left for the normal enrich route
            continue
        try:
            with spend_context(batch_id=batch_id, lead_id=r["id"]):
                buyer = verify_lead(pool, r, r["owner_email"], bucket)
        except (OutOfCredits, BudgetExceeded):
            counts["out_of_credits"] = len(rows) - done  # stay `cleaned`: running out is not "no buyer"
            break
        patch = {"status": Status.ENRICHED.value, "email_verified": True} if buyer else {"status": Status.NO_BUYER.value}
        db.table("leads").update(patch).eq("id", r["id"]).execute()
        key = "enriched" if buyer else "no_buyer"
        counts[key] = counts.get(key, 0) + 1
    return counts
