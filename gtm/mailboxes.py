"""Which Gmail mailbox sends which lead. A lead keeps one mailbox for its whole sequence."""

from __future__ import annotations

from collections import Counter
from datetime import date

from gtm.db import fetch_all


def assign_mailbox(db, lead_id: str, today: date | None = None, only: set[str] | None = None) -> str:
    lead = db.table("leads").select("mailbox_id").eq("id", lead_id).execute().data[0]
    if lead["mailbox_id"]:
        return lead["mailbox_id"]  # sticky, even if that mailbox is paused now: sending respects the pause
    today = today or date.today()
    usable = [
        m["id"] for m in db.table("mailboxes").select("id,enabled_on").eq("paused", False).execute().data
        if m["enabled_on"] and date.fromisoformat(m["enabled_on"]) <= today and (only is None or m["id"] in only)
    ]
    if not usable:
        raise RuntimeError("no enabled, unpaused mailbox: add one with `gtm mailbox add`")
    load = Counter(r["mailbox_id"] for r in fetch_all(lambda: db.table("leads").select("mailbox_id").not_.is_("mailbox_id", "null").order("id")))
    pick = min(usable, key=lambda i: load[i])
    db.table("leads").update({"mailbox_id": pick}).eq("id", lead_id).execute()
    return pick


def mailbox_address(db, mailbox_id: str) -> str:
    return db.table("mailboxes").select("address").eq("id", mailbox_id).execute().data[0]["address"]
