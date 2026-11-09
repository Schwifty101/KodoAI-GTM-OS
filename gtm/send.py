"""Send pass: the ONLY place a draft becomes an email. Per-mailbox daily ramp, pause on a bounce spike, suppression re-checked at send time."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from gtm.config import Settings, get_settings
from gtm.gmail import send_draft
from gtm.select import _blocklists, blocked_reason
from gtm.status import Status

STOPPED = {Status.REPLIED.value, Status.BOUNCED.value, Status.UNSUBSCRIBED.value, Status.SUPPRESSED.value, Status.BOOKED.value}
WINDOW_DAYS = 7  # bounce rate is judged over the last week of sends


def allowance(mailbox: dict, today: date, ramp_start: int, ramp_step: int, cap: int) -> int:
    if not mailbox.get("enabled_on"):
        return 0
    days = (today - date.fromisoformat(mailbox["enabled_on"])).days
    return 0 if days < 0 else min(cap, ramp_start + ramp_step * days)


def should_pause(sent: int, bounced: int, complaints: int, *, rate: float = 0.03, min_sends: int = 20) -> bool:
    """Any complaint pauses. A bounce rate only counts once there are enough sends to mean something."""
    return complaints >= 1 or (sent >= min_sends and bounced / sent > rate)


def _day(ts: str | None) -> str:
    return (ts or "")[:10]


def send_due(db, gmail_for, today: date, settings: Settings | None = None) -> dict[str, int]:
    """Send due drafts mailbox by mailbox. Follow-ups go before new leads. Returns counts."""
    s = settings or get_settings()
    out: Counter = Counter()
    suppressed, contacted = _blocklists(db)
    for mb in db.table("mailboxes").select("*").execute().data:
        if mb["paused"]:
            continue
        leads = {l["id"]: l for l in db.table("leads").select("*").eq("mailbox_id", mb["id"]).execute().data}
        touches = []
        ids = list(leads)
        for i in range(0, len(ids), 100):
            touches += db.table("touches").select("*").in_("lead_id", ids[i : i + 100]).execute().data
        since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
        recent = [t for t in touches if t["status"] == "sent" and _day(t["sent_at"]) >= since]
        bounced = len({t["lead_id"] for t in recent if leads[t["lead_id"]]["status"] == Status.BOUNCED.value})
        if should_pause(len(recent), bounced, 0, rate=s.pause_bounce_rate, min_sends=s.pause_min_sends):
            db.table("mailboxes").update({"paused": True, "paused_reason": f"bounce rate {bounced}/{len(recent)} sends in {WINDOW_DAYS} days"}).eq("id", mb["id"]).execute()
            out["paused"] += 1
            continue
        sent_today = sum(1 for t in touches if t["status"] == "sent" and _day(t["sent_at"]) == today.isoformat())
        room = allowance(mb, today, s.ramp_start, s.ramp_step, min(s.daily_cap, mb["daily_cap"])) - sent_today
        due = sorted((t for t in touches if t["status"] == "drafted" and (t["scheduled_for"] or "") <= today.isoformat()),
                     key=lambda t: (-t["touch_no"], t["scheduled_for"] or ""))
        for t in due:
            lead = leads[t["lead_id"]]
            if lead["status"] in STOPPED:
                db.table("touches").update({"status": "cancelled"}).eq("id", t["id"]).execute()
                out["cancelled"] += 1
                continue
            if lead["status"] != (Status.DRAFTED.value if t["touch_no"] == 1 else Status.SENT.value):
                continue
            blocked = blocked_reason(lead, suppressed, contacted if t["touch_no"] == 1 else set())
            if blocked == "suppressed":
                db.table("touches").update({"status": "cancelled"}).eq("id", t["id"]).execute()
                db.table("leads").update({"status": Status.SUPPRESSED.value, "reject_reason": blocked}).eq("id", lead["id"]).execute()
                out["cancelled"] += 1
                continue
            if blocked:
                out["held"] += 1  # already emailed this company: left as a draft for the operator to decide
                continue
            if room <= 0:
                out["deferred"] += 1
                continue
            try:
                thread = send_draft(gmail_for(mb["address"]), t["gmail_draft_id"])
            except Exception:
                out["errors"] += 1
                continue
            stamp = datetime.combine(today, datetime.now(timezone.utc).timetz()).isoformat()
            db.table("touches").update({"status": "sent", "sent_at": stamp, "gmail_thread_id": thread}).eq("id", t["id"]).execute()
            if t["touch_no"] == 1:
                db.table("leads").update({"status": Status.SENT.value}).eq("id", lead["id"]).execute()
            room -= 1
            out["sent"] += 1
    return dict(out)
