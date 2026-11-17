"""verify-sheet: Hunter-verify the emails imported from the sheet, inside the one-off import allowance."""

from __future__ import annotations

from gtm.budget import BudgetExceeded
from gtm.buyer import is_decision_maker, is_role_email, pick_buyer
from gtm.costs import spend_context
from gtm.hunter import OutOfCredits
from gtm.status import Status


def run_verify_sheet(db, pool, batch_id: str, limit: int | None = None, bucket: str = "hunter_import") -> dict[str, int]:
    """pool is always supplied by the caller (the CLI refuses without --confirm). A lead that cannot qualify
    (no named decision-maker, role address) fails without spending a credit."""
    q = (db.table("leads").select("id,owner_name,owner_title,owner_email").eq("batch_id", batch_id).eq("status", Status.CLEANED.value)
         .eq("email_source", "sheet").eq("email_verified", False).not_.is_("owner_email", "null"))
    rows = (q.limit(limit) if limit else q).execute().data
    counts: dict[str, int] = {}
    for done, r in enumerate(rows):
        buyer = None
        if (r.get("owner_name") or "").strip() and is_decision_maker(r.get("owner_title")) and not is_role_email(r["owner_email"]):
            first, _, last = r["owner_name"].strip().partition(" ")  # same split as gtm.enrich for saved names
            try:
                with spend_context(batch_id=batch_id, lead_id=r["id"]):
                    v = pool.verify_email(r["owner_email"], bucket)
            except (OutOfCredits, BudgetExceeded):
                counts["out_of_credits"] = len(rows) - done  # stay `cleaned`: running out is not "no buyer"
                break
            buyer = pick_buyer([{**v, "first_name": first, "last_name": last, "position": r["owner_title"]}])
        patch = {"status": Status.ENRICHED.value, "email_verified": True} if buyer else {"status": Status.NO_BUYER.value}
        db.table("leads").update(patch).eq("id", r["id"]).execute()
        key = "enriched" if buyer else "no_buyer"
        counts[key] = counts.get(key, 0) + 1
    return counts
