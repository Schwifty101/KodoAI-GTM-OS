"""Draft pass: Touch 1 by the model under mechanical checks, Touch 2 and 3 from fixed templates. Nothing here sends."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from gtm.config import Settings, get_settings
from gtm.gmail import create_draft
from gtm.mailboxes import assign_mailbox, mailbox_address
from gtm.select import _blocklists, blocked_reason
from gtm.status import Status

SYSTEM = (Path(__file__).parent / "data" / "draft_prompt.md").read_text()
# Names Soban's team may cite: MedSpa Touch-1 prompt section 8b. Re-read the portfolio before each batch.
APPROVED_CLIENTS = ["Rolls-Royce", "Saudi Aramco", "Patagonia", "Almarai", "Repligen", "Saudi Investment Bank", "MagPaiAnalytics", "TalisAI",
                    "Art of Education", "Kbean", "OrderCircle", "AirTrail"]
BANNED = ["i wanted to reach out", "i hope this finds you well", "touch base", "circle back", "quick question", "reach out", "synergy", "leverage",
          "best-in-class", "cutting-edge", "game-changing", "unlock", "empower", "seamless", "turnkey", "pain points"]
OFFER = re.compile(r"\b(demo|meeting|free trial|trial|audit|calendar|schedule a|book a (call|time)|15[- ]minute|quick call|hop on a call)\b", re.I)
SOFT_OUT = re.compile(r"\b(no worries|or not|if not|not right now|no pressure)\b", re.I)
LIMITS = {1: (45, 70), 2: (10, 35), 3: (15, 40)}  # words; Touch 1 counts everything, Touch 2 and 3 exclude greeting and signature
OFFSETS = {1: 0, 2: 3, 3: 7}


def touch_date(first_sent: date, touch_no: int) -> date:
    if touch_no not in OFFSETS:
        raise ValueError("there is no Touch 4")
    return first_sent + timedelta(days=OFFSETS[touch_no])


def footer(s: Settings) -> str:
    return "\n".join(v for v in (s.ad_disclosure, s.opt_out_line, s.postal_address) if v)


def _split(text: str) -> tuple[str | None, list[str], str | None]:
    paras = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    greeting = paras[0] if paras and paras[0].endswith(",") and len(paras[0].split()) <= 3 else None
    sig = paras[-1] if len(paras) > 1 and paras[-1].startswith("Soban") else None
    body = paras[(1 if greeting else 0): (len(paras) - 1 if sig else len(paras))]
    return greeting, body, sig


def check_draft(text: str, touch_no: int = 1) -> list[str]:
    """Mechanical rules from MedSpa/KodoAI-Cold-Outreach-Writing-Rules.md. Returns problem codes; empty means clean."""
    greeting, body, sig = _split(text)
    body_text = " ".join(body)
    problems = []
    if not greeting:
        problems.append("missing_greeting")
    if not sig or (touch_no == 1 and sig != "Soban | Founder, KodoAI"):
        problems.append("missing_signature")
    lo, hi = LIMITS[touch_no]
    n = len(text.split()) if touch_no == 1 else len(body_text.split())
    if n < lo:
        problems.append("too_short")
    if n > hi:
        problems.append("too_long")
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", body_text) if s]
    if touch_no == 1 and not 5 <= len(sentences) <= 8:
        problems.append("sentence_count")
    if body_text.count("?") != 1 or not sentences or not sentences[-1].endswith("?"):
        problems.append("not_one_question")
    low = text.lower()
    if "—" in text:
        problems.append("em_dash")
    if any(b in low for b in BANNED) or re.search(r"\bsolutions?\b", low):
        problems.append("banned_phrase")
    if OFFER.search(body_text):
        problems.append("offer")
    if re.search(r"\d", body_text):
        problems.append("number")
    if "bluegile" in low:
        problems.append("bluegile")
    if re.search(r"our customers|trusted by|clients include|customers include", low):
        problems.append("client_phrasing")
    if touch_no == 1:
        m = re.search(r"We've worked with ([^.]+)\.", text)
        if not m or "I'm Soban, founder of KodoAI." not in text:
            problems.append("missing_credibility")
        else:
            names = [x.strip() for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1)) if x.strip()]
            if not 2 <= len(names) <= 3:
                problems.append("client_count")
            if any(x not in APPROVED_CLIENTS for x in names):
                problems.append("unapproved_client")
        if sentences and SOFT_OUT.search(sentences[-1]):
            problems.append("soft_opt_out")
    elif "we've worked with" in low:
        problems.append("credibility_repeated")
    return problems


def build_followup(touch_no: int, first_name: str, company: str, objective: str) -> str:
    if touch_no == 2:
        return f"{first_name},\n\nIs {objective} something you're working on right now, or is it not a priority?\n\nSoban"
    if touch_no == 3:
        return (f"{first_name},\n\nWe're choosing med-spa partners who are ready to make {objective} a priority this quarter.\n\n"
                f"Is that where {company} is right now?\n\nSoban")
    raise ValueError("only Touch 2 and 3 are templates; there is no Touch 4")


def _prompt(lead: dict, problems: list[str]) -> str:
    sig, handoff = lead["signal"].get("current_signal"), lead["signal"]["relevant_handoff"]
    lane = "signal-led" if lead.get("signal_led") and sig else "relevance-led"
    facts = (f"Lane: {lane}. Buyer first name: {lead['owner_name'].split()[0]}. Company: {lead['name']}. Vector: {lead['vector']}.\n"
             f"Observed handoff: {handoff['text']}")
    if lane == "signal-led":
        facts += f"\nObserved signal ({sig['date']}): {sig['text']}"
    if problems:
        facts += f"\n\nYour previous draft broke these rules, fix them: {', '.join(problems)}."
    return facts


def draft_touch1(llm, lead: dict, attempts: int = 3) -> dict | None:
    problems: list[str] = []
    for _ in range(attempts):
        ans = llm(SYSTEM, _prompt(lead, problems))
        subject, body, objective = ans.get("subject") or "", ans.get("body") or "", (ans.get("objective") or "").strip()
        problems = check_draft(body, 1)
        if not re.match(r"^.+ / .+$", subject):
            problems.append("bad_subject")
        if not objective:
            problems.append("no_objective")
        if not problems:
            return {"subject": subject, "body": body, "objective": objective}
    return None


def _with_footer(body: str) -> str:
    f = footer(get_settings())
    return f"{body}\n\n{f}" if f else body


def _store(db, gmail_for, lead: dict, mailbox_id: str, touch_no: int, subject: str, body: str, objective: str, today: date, thread_id=None) -> None:
    draft_id = create_draft(gmail_for(mailbox_address(db, mailbox_id)), lead["owner_email"], subject, body, thread_id)
    db.table("touches").insert({"lead_id": lead["id"], "touch_no": touch_no, "status": "drafted", "gmail_draft_id": draft_id, "gmail_thread_id": thread_id,
                                "subject": subject, "body": body, "objective": objective, "scheduled_for": today.isoformat()}).execute()


def run_draft(db, llm, gmail_for, batch_id: str, today: date) -> int:
    rows = db.table("leads").select("*").eq("batch_id", batch_id).eq("status", Status.SELECTED.value).eq("approved", True).execute().data
    suppressed, contacted = _blocklists(db)
    done = 0
    for lead in rows:
        blocked = blocked_reason(lead, suppressed, contacted)
        if blocked:
            db.table("leads").update({"status": Status.SUPPRESSED.value, "reject_reason": blocked} if blocked == "suppressed" else {"reject_reason": blocked}).eq("id", lead["id"]).execute()
            continue
        try:
            d = draft_touch1(llm, lead)
        except Exception:
            continue  # stays `selected`, retried next run
        if not d:
            continue
        mailbox_id = assign_mailbox(db, lead["id"], today)
        _store(db, gmail_for, lead, mailbox_id, 1, d["subject"], _with_footer(d["body"]), d["objective"], today)
        db.table("leads").update({"status": Status.DRAFTED.value}).eq("id", lead["id"]).execute()
        done += 1
    return done


def run_followups(db, gmail_for, today: date) -> int:
    """Draft Touch 2 (Day 3) and Touch 3 (Day 7) in the Touch 1 thread. A reply, bounce or opt-out leaves the lead out of `sent`, so it stops here."""
    suppressed, _ = _blocklists(db)  # only opt-outs matter mid-sequence: we have of course already contacted these leads
    done = 0
    for lead in db.table("leads").select("*").eq("status", Status.SENT.value).execute().data:
        touches = {t["touch_no"]: t for t in db.table("touches").select("*").eq("lead_id", lead["id"]).execute().data}
        t1 = touches.get(1)
        if not t1 or t1["status"] != "sent" or not t1.get("sent_at"):
            continue
        n = 2 if 2 not in touches else 3 if 3 not in touches and touches[2]["status"] == "sent" else None
        if n is None or today < touch_date(date.fromisoformat(t1["sent_at"][:10]), n):
            continue
        if blocked_reason(lead, suppressed, set()):
            continue
        subject = "Re: " + re.sub(r"^Re:\s*", "", t1["subject"])
        body = build_followup(n, lead["owner_name"].split()[0], lead["name"], t1["objective"])
        _store(db, gmail_for, lead, lead["mailbox_id"], n, subject, _with_footer(body), t1["objective"], today, t1["gmail_thread_id"])
        done += 1
    return done
