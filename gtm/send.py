"""Send pass: the ONLY place a draft becomes an email. Per-mailbox daily ramp, pause on a bounce spike, suppression re-checked at send time."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from gtm.config import Settings, get_settings
from gtm.db import fetch_all
from gtm.gmail import create_draft, send_draft, thread_messages
from gtm.replies import run_replies
from gtm.select import _blocklists, blocked_reason
from gtm.status import Status

STOPPED = {Status.REPLIED.value, Status.BOUNCED.value, Status.UNSUBSCRIBED.value, Status.SUPPRESSED.value, Status.BOOKED.value}
WINDOW_DAYS = 7  # bounce rate is judged over the last week of sends
SEND_START, SEND_END = 9, 16  # local hours, Mon-Fri: design spec section 15 (owner guess, "9 to 4"); a lead with no tz uses Chicago


def in_window(now: datetime, tz: str | None) -> bool:
    local = now.astimezone(ZoneInfo(tz or "America/Chicago"))
    return local.weekday() < 5 and SEND_START <= local.hour < SEND_END


def is_test_lead(place_id: str) -> bool:
    return place_id.startswith(("TEST_", "REHEARSAL_"))


def sending_days(db, mailbox_id: str, before: date) -> int:
    """Distinct UTC days before `before` (and on or after the mailbox's ramp_from) on which it sent to a real lead: the ramp counts these, not calendar days."""
    start = db.table("mailboxes").select("ramp_from").eq("id", mailbox_id).execute().data[0]["ramp_from"] or ""
    rows = fetch_all(lambda: db.table("touches").select("sent_at,leads!inner(place_id)").eq("status", "sent").eq("leads.mailbox_id", mailbox_id).lt("sent_at", before.isoformat()).order("id"))
    days = {_day(r["sent_at"]) for r in rows if not is_test_lead(r["leads"]["place_id"])}
    return sum(d >= start for d in days)


def allowance(mailbox: dict, days_sent: int, ramp_start: int, ramp_step: int, cap: int) -> int:
    if not mailbox.get("enabled_on") or mailbox.get("paused"):
        return 0
    return min(cap, ramp_start + ramp_step * days_sent)


def window_end(now: datetime, tz: str | None) -> datetime:
    z = ZoneInfo(tz or "America/Chicago")
    d = now.astimezone(z)
    return datetime(d.year, d.month, d.day, SEND_END, tzinfo=z)


def pick_send_at(now: datetime, tz: str | None, rng: random.Random) -> datetime | None:
    """A random instant in [now, 16:00 local), or None when `now` is outside the lead's window."""
    return now + (window_end(now, tz) - now) * rng.random() if in_window(now, tz) else None


def _touches(db, mailbox_id: str, status: str, since: str | None = None) -> list[dict]:
    """The mailbox's touches in one status, each with its lead's fields under `leads`."""
    def q():
        r = db.table("touches").select("*,leads!inner(status,tz,owner_email,domain)").eq("leads.mailbox_id", mailbox_id).eq("status", status)
        return (r.gte("sent_at", since) if since else r).order("id")
    return fetch_all(q)


def schedule_approved(db, mailbox: dict, now: datetime, settings: Settings, rng: random.Random | None = None, anytime: bool = False) -> int:
    """Approved -> scheduled with a random send_at in the lead's window today, while today's allowance has room. Follow-ups first."""
    rng, now = rng or random.Random(), now.astimezone(timezone.utc)
    mb = mailbox["id"]
    taken = len(_touches(db, mb, "scheduled")) + len(_touches(db, mb, "sending")) + len(_touches(db, mb, "sent", now.date().isoformat()))
    room = allowance(mailbox, sending_days(db, mb, now.date()), settings.ramp_start, settings.ramp_step, min(settings.daily_cap, mailbox["daily_cap"])) - taken
    suppressed, contacted = _blocklists(db)
    n = 0
    for t in sorted(_touches(db, mb, "approved"), key=lambda t: (-t["touch_no"], t["approved_at"] or "")):
        if room <= 0:
            break
        lead = t["leads"]
        if lead["status"] != (Status.DRAFTED.value if t["touch_no"] == 1 else Status.SENT.value) or blocked_reason(lead, suppressed, contacted if t["touch_no"] == 1 else set()):
            continue
        at = now if anytime else pick_send_at(now, lead.get("tz"), rng)
        if at is None:
            continue  # outside its window now: stays approved, a later tick picks it up
        if db.table("touches").update({"status": "scheduled", "send_at": at.astimezone(timezone.utc).isoformat()}).eq("id", t["id"]).eq("status", "approved").execute().data:
            room -= 1
            n += 1
    return n


def _cancel(db, t: dict) -> None:
    db.table("touches").update({"status": "cancelled"}).eq("id", t["id"]).eq("status", "scheduled").execute()


def send_scheduled(db, gmail_for, mailbox: dict, now: datetime, settings: Settings, anytime: bool = False) -> dict[str, int]:
    """Send scheduled touches whose send_at has come. Re-checks stop/suppression, claims scheduled -> sending atomically, then drafts and sends the stored text."""
    out: Counter = Counter()
    suppressed, contacted = _blocklists(db)
    svc = gmail_for(mailbox["address"])
    due = [t for t in _touches(db, mailbox["id"], "scheduled") if datetime.fromisoformat(t["send_at"]) <= now]
    for t in sorted(due, key=lambda t: (-t["touch_no"], t["send_at"])):
        lead = t["leads"]
        blocked = blocked_reason(lead, suppressed, contacted if t["touch_no"] == 1 else set())
        if lead["status"] in STOPPED or blocked:
            _cancel(db, t)
            if blocked == "suppressed":
                db.table("leads").update({"status": Status.SUPPRESSED.value, "reject_reason": blocked}).eq("id", t["lead_id"]).execute()
            out["cancelled"] += 1
            continue
        if not (anytime or in_window(now, lead.get("tz"))):
            out["deferred"] += 1
            continue
        if not db.table("touches").update({"status": "sending"}).eq("id", t["id"]).eq("status", "scheduled").execute().data:
            continue  # another sender claimed it
        try:
            reply_to = thread_messages(svc, t["gmail_thread_id"])[0]["headers"]["message-id"] if t["touch_no"] > 1 else None
            draft = create_draft(svc, lead["owner_email"], t["subject"], t["body"], t["gmail_thread_id"], reply_to)
        except Exception:
            db.table("touches").update({"status": "scheduled"}).eq("id", t["id"]).execute()
            out["errors"] += 1
            continue
        try:
            thread = send_draft(svc, draft)
        except Exception:
            db.table("touches").update({"gmail_draft_id": draft}).eq("id", t["id"]).execute()  # stays `sending`: the owner decides (Mark sent / Mark failed)
            out["stranded"] += 1
            continue
        db.table("touches").update({"status": "sent", "sent_at": now.isoformat(), "gmail_draft_id": draft, "gmail_thread_id": thread}).eq("id", t["id"]).execute()
        if t["touch_no"] == 1:
            db.table("leads").update({"status": Status.SENT.value}).eq("id", t["lead_id"]).execute()
        out["sent"] += 1
    return dict(out)


def should_pause(sent: int, bounced: int, complaints: int, *, rate: float = 0.03, min_sends: int = 20) -> bool:
    """Any complaint pauses. A bounce rate only counts once there are enough sends to mean something."""
    return complaints >= 1 or (sent >= min_sends and bounced / sent > rate)


def _day(ts: str | None) -> str:
    return (ts or "")[:10]


def send_due(db, gmail_for, today: date, settings: Settings | None = None, now: datetime | None = None, anytime: bool = False) -> dict[str, int]:
    """Send due drafts mailbox by mailbox. Follow-ups go before new leads. A draft outside its lead's weekday window stays a draft (`deferred`) unless anytime. Returns counts."""
    s = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    out: Counter = Counter()
    suppressed, contacted = _blocklists(db)
    for mb in db.table("mailboxes").select("*").execute().data:
        if mb["paused"]:
            continue
        leads = {l["id"]: l for l in fetch_all(lambda: db.table("leads").select("*").eq("mailbox_id", mb["id"]).order("id"))}
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
        room = allowance(mb, sending_days(db, mb["id"], today), s.ramp_start, s.ramp_step, min(s.daily_cap, mb["daily_cap"])) - sent_today
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
            if room <= 0 or not (anytime or in_window(now, lead.get("tz"))):
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


def send_with_reply_check(db, gmail_for, llm, today: date, settings: Settings | None = None, now: datetime | None = None, anytime: bool = False, **fetchers) -> dict:
    """Read replies and bounces first, so a lead who said stop on Day 2 is `unsubscribed` (and its Touch 2 cancelled) before Day 3 sends."""
    replies = run_replies(db, gmail_for, llm, **fetchers)
    return {"replies": replies, "send": send_due(db, gmail_for, today, settings, now, anytime)}
