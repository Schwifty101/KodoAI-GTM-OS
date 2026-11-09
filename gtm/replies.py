"""Reply pass: read replies and bounces, stop the sequence, and honour opt-outs in the same run."""

from __future__ import annotations

import re
from collections import Counter

from gtm.gmail import recent_bounces, thread_messages
from gtm.status import Status

KINDS = {"positive", "negative", "other"}
SYSTEM = ('Classify a reply to a cold email from KodoAI. positive = interested or asks for more; negative = declines; other = anything else '
          '(a question, a referral, unclear). Reply with JSON {"kind": "positive" | "negative" | "other"}.')
BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster", re.I)
BOUNCE_SUBJECT = re.compile(r"delivery status notification|undeliverable|mail delivery failed|returned mail", re.I)
AUTO_SUBJECT = re.compile(r"^\s*(automatic reply|auto[- ]?reply|autoreply|out of office)\b", re.I)
AUTO_BODY = re.compile(r"out of (the )?office|automatic reply|auto-?reply|i am currently (away|out)|on (annual )?leave until|on vacation", re.I)
OPT_OUT = re.compile(r"unsubscribe|stop (emailing|contacting|sending|email)|take me off|remove me|please remove|do not (contact|email)|don'?t (contact|email)|opt[- ]?out|no more emails", re.I)
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com"}


def new_text(body: str) -> str:
    """The reply itself, without the quoted copy of our own email (whose footer could say 'stop')."""
    body = body.replace("’", "'")
    cut = re.split(r"\n\s*On .{0,150}wrote:|\n-{2,}\s*Original Message\s*-{2,}|\nFrom: .*\nSent:", body, maxsplit=1, flags=re.S)[0]
    return "\n".join(ln for ln in cut.splitlines() if not ln.lstrip().startswith(">")).strip()


def classify_reply(msg: dict, llm=None) -> str:
    """bounce, auto_reply and opt_out are decided by rules; the model only splits positive, negative and other."""
    h = msg.get("headers", {})
    if BOUNCE_FROM.search(msg.get("from", "")) or BOUNCE_SUBJECT.search(msg.get("subject", "")):
        return "bounce"
    text = new_text(msg.get("body", ""))
    if (h.get("auto-submitted", "no").lower() != "no" or h.get("precedence", "").lower() in {"auto_reply", "bulk", "junk"}
            or "x-autoreply" in h or AUTO_SUBJECT.search(msg.get("subject", "")) or AUTO_BODY.search(text)):
        return "auto_reply"
    if OPT_OUT.search(text):
        return "opt_out"
    if llm:
        try:
            kind = llm(SYSTEM, text[:2000]).get("kind")
            return kind if kind in KINDS else "other"
        except Exception:
            return "other"
    return "other"


def _address(frm: str) -> str:
    m = re.search(r"[\w.+-]+@[\w.-]+", frm)
    return m.group(0).lower() if m else ""


def apply_reply(db, lead_id: str, kind: str, sender: str | None = None) -> None:
    if kind == "auto_reply":
        return  # an out-of-office is not an answer: the sequence carries on
    lead = db.table("leads").select("owner_email,domain").eq("id", lead_id).execute().data[0]
    db.table("touches").update({"status": "cancelled"}).eq("lead_id", lead_id).eq("status", "drafted").execute()
    last = db.table("touches").select("id").eq("lead_id", lead_id).eq("status", "sent").order("touch_no", desc=True).limit(1).execute().data
    if last:
        db.table("touches").update({"outcome": kind}).eq("id", last[0]["id"]).execute()
    status = {"opt_out": Status.UNSUBSCRIBED, "bounce": Status.BOUNCED}.get(kind, Status.REPLIED)
    db.table("leads").update({"status": status.value}).eq("id", lead_id).execute()
    if kind == "opt_out":
        rows = [{"email": e, "reason": "opt-out reply"} for e in {lead["owner_email"], sender} if e]
        if lead["domain"] and lead["domain"] not in FREE_MAIL:  # the business's own domain, never a shared mail provider
            rows.append({"domain": lead["domain"], "reason": "opt-out reply"})
        db.table("suppression").insert(rows).execute()
    elif kind == "bounce" and lead["owner_email"]:
        db.table("suppression").insert({"email": lead["owner_email"], "reason": "bounce"}).execute()


def run_replies(db, gmail_for, llm, thread_messages=thread_messages, recent_bounces=recent_bounces) -> dict[str, int]:
    counts: Counter = Counter()
    for mb in db.table("mailboxes").select("*").execute().data:
        svc = gmail_for(mb["address"])
        active = {l["id"]: l for l in db.table("leads").select("id,owner_email").eq("mailbox_id", mb["id"]).eq("status", Status.SENT.value).execute().data}
        for lead_id in list(active):
            last = db.table("touches").select("gmail_thread_id").eq("lead_id", lead_id).eq("status", "sent").order("touch_no", desc=True).limit(1).execute().data
            if not last or not last[0]["gmail_thread_id"]:
                continue
            replies = [m for m in thread_messages(svc, last[0]["gmail_thread_id"]) if mb["address"].lower() not in m["from"].lower()]
            if not replies:
                continue
            kind = classify_reply(replies[-1], llm)
            counts[kind] += 1
            apply_reply(db, lead_id, kind, _address(replies[-1]["from"]))
            if kind != "auto_reply":
                active.pop(lead_id)
        for b in recent_bounces(svc):
            for lead_id, lead in list(active.items()):
                if lead["owner_email"] and lead["owner_email"].lower() in b["body"].lower():
                    apply_reply(db, lead_id, "bounce")
                    counts["bounce"] += 1
                    active.pop(lead_id)
    return dict(counts)
