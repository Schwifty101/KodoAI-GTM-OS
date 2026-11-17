"""redraft pass: regenerate a batch's unsent Touch 1 drafts with an owner instruction."""

from __future__ import annotations

import sys
from datetime import date

from gtm.budget import BudgetExceeded
from gtm.costs import spend_context
from gtm.db import fetch_all
from gtm.draft import _with_footer, draft_touch1
from gtm.select import _blocklists, blocked_reason
from gtm.status import Status

REDRAFTABLE = ["drafted", "held", "edited"]


def run_redraft(db, llm, batch_id: str, instruction: str, today: date) -> int:  # `today` is part of the planned interface, unused
    instruction = (instruction or "").strip()
    if not instruction:
        raise ValueError("an empty instruction would redraft nothing new")
    db.table("batches").update({"draft_instruction": instruction}).eq("id", batch_id).execute()
    suppressed, contacted = _blocklists(db)
    done = skipped_edited = 0
    for lead in fetch_all(lambda: db.table("leads").select("*").eq("batch_id", batch_id).order("id")):
        if lead["status"] != Status.DRAFTED.value or blocked_reason(lead, suppressed, contacted):
            continue  # replied, bounced, suppressed...: no model call
        for t in db.table("touches").select("id,subject,body").eq("lead_id", lead["id"]).eq("touch_no", 1).in_("status", REDRAFTABLE).execute().data:
            try:
                with spend_context(batch_id=batch_id, lead_id=lead["id"]):
                    d = draft_touch1(llm, lead, instruction=instruction)
            except BudgetExceeded:
                raise  # the worker records paused_budget; the remaining drafts stay as they are
            except Exception as e:
                print(f"redraft failed {lead.get('name')}: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
                db.table("touches").update({"status": "held", "problems": ["redraft_failed"]}).eq("id", t["id"]).in_("status", REDRAFTABLE).eq("subject", t["subject"]).eq("body", t["body"]).execute()
                continue
            res = db.table("touches").update({
                "subject": d["subject"], "body": _with_footer(d["body"]) if d["body"] else "", "objective": d["objective"], "problems": d["problems"],
                "status": "held" if d["problems"] else "drafted", "approved_at": None,
            }).eq("id", t["id"]).in_("status", REDRAFTABLE).eq("subject", t["subject"]).eq("body", t["body"]).execute()  # an approval or owner edit that landed meanwhile wins
            if res.data:
                done += 1
            else:
                skipped_edited += 1
    if skipped_edited:
        print(f"skipped_edited {skipped_edited} (changed during the model call)")
    return done
