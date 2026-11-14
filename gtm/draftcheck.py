"""check-drafts pass: re-run the mechanical rules on touches the owner edited in the UI."""

from __future__ import annotations

import re

from gtm.draft import check_draft


def run_check_drafts(db) -> int:
    rows = db.table("touches").select("id,touch_no,subject,body").eq("status", "edited").execute().data
    for t in rows:
        problems = check_draft(t["body"] or "", t["touch_no"])
        if t["touch_no"] == 1 and not re.match(r"^.+ / .+$", t["subject"] or ""):
            problems.append("bad_subject")
        db.table("touches").update({"status": "held" if problems else "drafted", "problems": problems}).eq("id", t["id"]).eq("status", "edited").execute()
    return len(rows)
