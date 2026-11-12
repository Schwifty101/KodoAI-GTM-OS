"""Select pass: rules decide who is emailable; the model only phrases the one-line reason shown on the Review page."""

from __future__ import annotations

from gtm.db import fetch_all
from gtm.signals import VECTORS
from gtm.costs import spend_context
from gtm.status import Status

REASON_SYSTEM = (
    "Write one plain sentence (at most 25 words) saying why this med spa is worth emailing, using only the facts given. "
    'Reply with JSON {"reason": str}. No numbers beyond the ones given and no claims about their performance.'
)


def blocked_reason(lead: dict, suppressed: set[str], contacted: set[str]) -> str | None:
    """One entry (an email or a domain) blocks the whole company: MedSpa allows one Touch 1 per company."""
    email = (lead.get("owner_email") or "").lower()
    keys = {email, email.split("@")[-1], (lead.get("domain") or "").lower()} - {""}
    return "suppressed" if keys & suppressed else "already_contacted" if keys & contacted else None


def select_decision(lead: dict, suppressed: set[str], contacted: set[str]) -> tuple[bool, str]:
    """(selected?, code). suppressed and contacted hold lowercase emails AND domains, so one entry blocks a whole company."""
    if lead.get("status") != Status.SIGNALLED.value:
        return False, "not_signalled"
    email = (lead.get("owner_email") or "").lower()
    if not email or lead.get("email_verified") is not True:
        return False, "no_email"
    blocked = blocked_reason(lead, suppressed, contacted)
    if blocked:
        return False, blocked
    handoff = (lead.get("signal") or {}).get("relevant_handoff")
    if lead.get("vector") not in VECTORS or not handoff:
        return False, "no_handoff"
    return True, "signal-led" if lead.get("signal_led") else "relevance-led"


def _fallback(lead: dict, lane: str) -> str:
    sig, handoff = lead["signal"].get("current_signal"), lead["signal"]["relevant_handoff"]
    return f"{sig['text']} ({sig['date']}); {handoff['text']}" if lane == "signal-led" and sig else f"No dated signal; {handoff['text']}"


def _reason(llm, lead: dict, lane: str) -> str:
    sig, handoff = lead["signal"].get("current_signal"), lead["signal"]["relevant_handoff"]
    facts = f"Business: {lead['name']}. Buyer: {lead.get('owner_title')}. Lane: {lane}. Vector: {lead['vector']}. Handoff: {handoff['text']}."
    if sig:
        facts += f" Signal ({sig['date']}): {sig['text']}."
    try:
        text = llm(REASON_SYSTEM, facts).get("reason")
    except Exception:
        text = None
    return text.strip() if isinstance(text, str) and text.strip() else _fallback(lead, lane)


def _blocklists(db) -> tuple[set[str], set[str]]:
    sup = set()
    for r in fetch_all(lambda: db.table("suppression").select("email,domain").order("id")):
        sup |= {v.lower() for v in (r["email"], r["domain"]) if v}
    sent = [t["lead_id"] for t in fetch_all(lambda: db.table("touches").select("lead_id").eq("status", "sent").order("id"))]
    contacted = set()
    for i in range(0, len(sent), 100):
        for r in db.table("leads").select("owner_email,domain").in_("id", sent[i : i + 100]).execute().data:
            contacted |= {v.lower() for v in (r["owner_email"], r["domain"]) if v}
    return sup, contacted


def run_select(db, llm, batch_id: str) -> int:
    rows = db.table("leads").select("*").eq("batch_id", batch_id).eq("status", Status.SIGNALLED.value).execute().data
    suppressed, contacted = _blocklists(db)
    selected = 0
    for lead in rows:
        ok, code = select_decision(lead, suppressed, contacted)
        if ok:
            with spend_context(batch_id=batch_id, lead_id=lead["id"]):
                reason = _reason(llm, lead, code)
            patch = {"status": Status.SELECTED.value, "select_reason": reason, "reject_reason": None}
            selected += 1
        elif code == "suppressed":
            patch = {"status": Status.SUPPRESSED.value, "reject_reason": code}
        else:
            patch = {"reject_reason": code}
        db.table("leads").update(patch).eq("id", lead["id"]).execute()
    return selected
