"""check-drafts pass: re-run the mechanical rules on touches the owner edited in the UI."""

from __future__ import annotations

from gtm.draft import check_draft, check_subject, strip_footer


def run_check_drafts(db, ids: list[str] | None = None) -> int:
    """`ids` limits the pass to those touches (tests); None checks every edited touch."""
    q = db.table("touches").select("id,touch_no,subject,body").eq("status", "edited")
    rows = (q.in_("id", ids) if ids is not None else q).execute().data
    for t in rows:
        problems = check_draft(strip_footer(t["body"] or ""), t["touch_no"]) + check_subject(t["subject"], t["touch_no"])
        # the equality guards leave a row edited again mid-check for the next run
        db.table("touches").update({"status": "held" if problems else "drafted", "problems": problems, "approved_at": None}) \
            .eq("id", t["id"]).eq("status", "edited").eq("body", t["body"]).eq("subject", t["subject"]).execute()
    return len(rows)
