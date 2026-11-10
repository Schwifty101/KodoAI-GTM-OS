"""Signals pass: judge each enriched lead's own website against MedSpa Touch-1 section 4. Code, not the model, gates what is stored:
every signal and handoff must quote text that is actually on a fetched page, and a signal must carry a real, recent date."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from gtm.sitescrape import _lines, http_fetch
from gtm.status import Status

VECTORS = {"conversion_recovery", "capacity", "rebooking_retention"}
PATHS = ["/", "/book", "/booking", "/book-now", "/contact", "/about", "/careers", "/jobs", "/news", "/blog", "/locations", "/memberships", "/specials"]
MAX_PAGE_CHARS, MAX_TOTAL_CHARS = 3000, 9000  # Groq free tier is 8K tokens a minute (docs/spikes/llm.md)
PLATFORMS = {"zenoti": "Zenoti", "joinblvd": "Boulevard", "blvd.me": "Boulevard", "vagaro": "Vagaro", "aestheticrecord": "Aesthetic Record",
             "patientnow": "PatientNow", "mindbodyonline": "Mindbody", "acuityscheduling": "Acuity"}
SYSTEM = (Path(__file__).parent / "data" / "signal_prompt.md").read_text()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def detect_platform(html: str) -> str | None:
    low = html.lower()
    return next((name for key, name in PLATFORMS.items() if key in low), None)


def fetch_evidence(lead: dict, fetch=http_fetch) -> dict:
    pages, platform, total = [], None, 0
    for path in PATHS:
        url = f"https://{lead['domain']}{path}"
        html = fetch(url)
        if not html:
            continue
        platform = platform or detect_platform(html)
        text = "\n".join(_lines(html))[:MAX_PAGE_CHARS]
        if text and total + len(text) <= MAX_TOTAL_CHARS:
            pages.append({"url": url, "text": text})
            total += len(text)
    return {"pages": pages, "platform": platform}


def validate_signal(sig: dict, today: date, max_age_days: int) -> bool:
    """A signal needs a URL and a real ISO date that is neither in the future nor older than max_age_days."""
    if not sig or not sig.get("url") or not sig.get("date"):
        return False
    try:
        age = (today - date.fromisoformat(sig["date"])).days
    except ValueError:
        return False
    return 0 <= age <= max_age_days


def _date_on_page(d: date, text: str) -> bool:
    """The model's date must be visible in the page text in a common format; an undated page cannot ground a 'current' signal."""
    t = re.sub(r"\s+", " ", text.lower())
    full, abbr = d.strftime("%B").lower(), d.strftime("%b").lower()
    forms = {d.isoformat(), f"{d.month}/{d.day}/{d.year}", f"{d.month:02d}/{d.day:02d}/{d.year}"}
    for m in {full, abbr, abbr + "."}:
        forms |= {f"{m} {d.day}, {d.year}", f"{m} {d.day} {d.year}", f"{d.day} {m} {d.year}", f"{d.day:02d} {m} {d.year}"}
    return any(f in t for f in forms)


def _grounded(item: dict | None, pages: list[dict]) -> bool:
    if not item or not item.get("url") or not item.get("quote"):
        return False
    page = next((p for p in pages if p["url"] == item["url"]), None)
    return bool(page) and _norm(item["quote"]) in _norm(page["text"])


def judge_to_signal(raw: dict, pages: list[dict], today: date, max_age_days: int) -> tuple[dict, str | None, bool]:
    signal = raw.get("current_signal")
    if not (_grounded(signal, pages) and validate_signal(signal, today, max_age_days)):
        signal = None
    else:
        page = next(p for p in pages if p["url"] == signal["url"])
        if not _date_on_page(date.fromisoformat(signal["date"]), page["text"]):
            signal = None  # a date the model supplied but the page does not show
    handoff = raw.get("relevant_handoff") if _grounded(raw.get("relevant_handoff"), pages) else None
    vector = raw.get("vector") if raw.get("vector") in VECTORS and handoff else None
    record = {
        "current_signal": signal, "relevant_handoff": handoff,
        "likely_objective": raw.get("likely_objective"), "reason_to_respond": raw.get("reason_to_respond"), "platform": raw.get("platform"),
        "evidence_strength": {"current_signal": "observed" if signal else "unknown", "relevant_handoff": "observed" if handoff else "unknown",
                              "likely_objective": "inference"},
        "judged_on": today.isoformat(),
    }
    return record, vector, bool(signal and handoff and vector)


def _prompt(lead: dict, ev: dict, today: date, max_age_days: int) -> str:
    pages = "\n\n".join(f"[PAGE {p['url']}]\n{p['text']}" for p in ev["pages"])
    return (f"Today: {today}. A signal must be no older than {max_age_days} days.\n"
            f"Business: {lead['name']} ({lead['domain']}), {lead.get('city') or ''}. Booking platform detected in links: {ev['platform'] or 'none'}.\n\n{pages}")


def run_signals(db, llm, evidence, batch_id: str, today: date, max_age_days: int) -> dict[str, int]:
    rows = db.table("leads").select("id,domain,name,city").eq("batch_id", batch_id).eq("status", Status.ENRICHED.value).execute().data
    counts: dict[str, int] = {}

    def bump(k):
        counts[k] = counts.get(k, 0) + 1

    for lead in rows:
        ev = evidence(lead)
        if ev["pages"]:
            try:
                raw = llm(SYSTEM, _prompt(lead, ev, today, max_age_days))
            except Exception:
                bump("llm_error")  # stays `enriched`, retried next run
                continue
        else:
            raw = {}
        record, vector, signal_led = judge_to_signal(raw, ev["pages"], today, max_age_days)
        db.table("leads").update({"status": Status.SIGNALLED.value, "signal": record, "vector": vector, "signal_led": signal_led}).eq("id", lead["id"]).execute()
        bump("signal_led" if signal_led else "relevance_led" if vector else "no_handoff")
    return counts
