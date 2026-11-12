"""Reply pass: read replies and bounces, stop the sequence, and honour opt-outs in the same run."""

from __future__ import annotations

import re
from collections import Counter

from gtm.costs import spend_context
from gtm.db import fetch_all
from gtm.gmail import recent_bounces, thread_messages
from gtm.status import Status

KINDS = {"positive", "negative", "other"}
SYSTEM = ('Classify a reply to a cold email from KodoAI. positive = interested or asks for more; negative = declines; other = anything else '
          '(a question, a referral, unclear). Reply with JSON {"kind": "positive" | "negative" | "other"}.')
BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster", re.I)
BOUNCE_SUBJECT = re.compile(r"delivery status notification|undeliverable|mail delivery failed|returned mail", re.I)
AUTO_SUBJECT = re.compile(r"^\s*(automatic reply|auto[- ]?reply|autoreply|out of office)\b", re.I)
AUTO_BODY = re.compile(r"out of (the )?office|automatic reply|auto-?reply|i am currently (away|out)|on (annual )?leave until|on vacation", re.I)
OPT_OUT = re.compile(r"unsubscribe|stop (emailing|contacting|sending|email)|take me off|remove me|please remove|do not (contact|email)|don'?t (contact|email|call)|opt[- ]?out|no more emails", re.I)
# Local classifier: negative is an allow-list (a wrong "no" suppresses the lead for good): the whole reply must be a bare decline and nothing else.
NEG_FULL = re.compile(r"(?:(?:hi|hello|hey)(?: [a-z]+)?[\s,.!-]+)?(?:(?:(?:we are|we're|i am|i'm|we) )?(?:not interested|not for us)|no thanks|no thank you|no"
                      r"|(?:we're|we are) (?:all set|good|covered)|(?:we )?already have (?:a|an|someone|a provider|a system))(?:[\s,.!-]+(?:thanks|thank you|sorry|at all|really|please))*[\s,.!-]*", re.I)
SIGNATURE = re.compile(r"\n[ \t]*(?:sent from my (?:iphone|ipad|ipod|android|(?:samsung )?galaxy(?: [a-z]?\d{1,3}(?: ultra| plus| fe| \+)?)?|blackberry|phone|mobile device|windows phone)|get outlook for (?:ios|android))[ \t]*\.?\s*\Z", re.I)  # only a standard last line
# A decline cue anywhere: only stops a positive cue from winning over a mixed reply.
NEG_CUE = re.compile(r"\bnot interested\b|\bno thanks\b|\bno thank you\b|\bnot for us\b|\bnot a fit\b|\bwe(?:'re| are) (?:all set|good|covered)\b"
                     r"|\balready have (?:a|an|someone|a provider|a system)\b|\bnot looking\b(?! forward)|^\W*no\W*$", re.I)
POS_CUE = re.compile(r"\btell me more\b|\bsounds (?:good|interesting)\b|\b(?:i|we)(?:'m|'re| am| are) interested\b|\blet'?s (?:talk|chat|connect|schedule|set up)\b"
                     r"|\bsend (?:me )?(?:more )?(?:info|information|details)\b|\bhow much\b|\bwhat(?:'?s| is) the (?:price|pricing|cost)\b|\b(?:book|schedule) a (?:call|demo)\b|\bcall me\b|^\W*yes(?: please)?\W*$", re.I)
# Deferral cues keep a positive from being decided locally.
DEFER_CUE = re.compile(r"\b(?:not right now|maybe|not sure|next|\blater|circle back|reach out|check back|for now|at this time|at the moment|this year|in \d+ (?:days?|weeks?|months?)"
                       r"|spring|summer|fall|autumn|winter|january|february|march|april|may|june|july|august|september|october|november|december)\b", re.I)
FREE_MAIL = {"gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com"}


def new_text(body: str) -> str:
    """The reply itself, without the quoted copy of our own email (whose footer could say 'stop')."""
    body = body.replace("’", "'")
    cut = re.split(r"\n\s*On .{0,150}wrote:|\n-{2,}\s*Original Message\s*-{2,}|\nFrom: .*\nSent:", body, maxsplit=1, flags=re.S)[0]
    return "\n".join(ln for ln in cut.splitlines() if not ln.lstrip().startswith(">")).strip()


def local_kind(text: str) -> str | None:
    """negative only for a bare decline, positive only for a clear cue with no decline or deferral; None sends it to the model."""
    clean = SIGNATURE.sub("", text).strip()
    if len(clean.split()) <= 6 and NEG_FULL.fullmatch(clean):
        return "negative"
    return "positive" if POS_CUE.search(clean) and not NEG_CUE.search(clean) and not DEFER_CUE.search(clean) else None


def classify_reply(msg: dict, llm=None) -> str:
    """bounce, auto_reply and opt_out are decided by rules; the model only splits positive, negative and other."""
    h = msg.get("headers", {})
    if BOUNCE_FROM.search(msg.get("from", "")) or BOUNCE_SUBJECT.search(msg.get("subject", "")):
        return "bounce"
    text = new_text(msg.get("body", ""))
    if (h.get("auto-submitted", "no").lower() != "no" or h.get("precedence", "").lower() in {"auto_reply", "bulk", "junk"}
            or "x-autoreply" in h or AUTO_SUBJECT.search(msg.get("subject", ""))):
        return "auto_reply"  # machine-marked: headers and subject are reliable
    if OPT_OUT.search(text):
        return "opt_out"  # before the body check: "back from vacation, please remove me" is a person asking to stop
    if AUTO_BODY.search(text):
        return "auto_reply"
    if kind := local_kind(text):
        return kind
    if llm:
        try:
            kind = llm(SYSTEM, text[:2000]).get("kind")
            return kind if kind in KINDS else "other"
        except Exception:
            return "other"
    return "other"


PRIORITY = {"bounce": 0, "opt_out": 1, "positive": 2, "other": 2, "negative": 2.5, "auto_reply": 3}


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
    if kind in {"opt_out", "negative"}:
        reason = "opt-out reply" if kind == "opt_out" else "not-interested"
        rows = [{"email": e, "reason": reason} for e in {lead["owner_email"], sender} if e]
        if lead["domain"] and lead["domain"] not in FREE_MAIL:  # the business's own domain, never a shared mail provider
            rows.append({"domain": lead["domain"], "reason": reason})
        db.table("suppression").insert(rows).execute()
    elif kind == "bounce" and lead["owner_email"]:
        db.table("suppression").insert({"email": lead["owner_email"], "reason": "bounce"}).execute()


def _classify_for(m: dict, llm, lead_id: str) -> str:
    with spend_context(lead_id=lead_id):  # the model's cost row names the lead
        return classify_reply(m, llm)


def run_replies(db, gmail_for, llm, thread_messages=thread_messages, recent_bounces=recent_bounces) -> dict[str, int]:
    counts: Counter = Counter()
    for mb in db.table("mailboxes").select("*").execute().data:
        svc = gmail_for(mb["address"])
        active = {l["id"]: l for l in fetch_all(lambda: db.table("leads").select("id,owner_email").eq("mailbox_id", mb["id"]).eq("status", Status.SENT.value).order("id"))}
        for lead_id in list(active):
            sent = db.table("touches").select("gmail_thread_id").eq("lead_id", lead_id).eq("status", "sent").order("touch_no").execute().data
            threads = list(dict.fromkeys(t["gmail_thread_id"] for t in sent if t["gmail_thread_id"]))  # every sent touch's thread, not just the latest
            inbound = [m for tid in threads for m in thread_messages(svc, tid) if mb["address"].lower() not in m["from"].lower()]
            if not inbound:
                continue
            ranked = sorted(((_classify_for(m, llm, lead_id), m) for m in inbound), key=lambda km: PRIORITY[km[0]])  # stable: bounce, opt-out, then a real reply, then auto-reply
            kind, m = ranked[0]
            counts[kind] += 1
            apply_reply(db, lead_id, kind, _address(m["from"]))
            if kind != "auto_reply":
                active.pop(lead_id)
        for b in recent_bounces(svc):
            for lead_id, lead in list(active.items()):
                if lead["owner_email"] and lead["owner_email"].lower() in b["body"].lower():
                    apply_reply(db, lead_id, "bounce")
                    counts["bounce"] += 1
                    active.pop(lead_id)
    return dict(counts)
