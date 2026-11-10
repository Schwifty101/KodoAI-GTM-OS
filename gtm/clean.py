"""Clean pass: plain rules, no LLM. Drops leads that are not worth a Hunter credit."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from gtm.db import fetch_all
from gtm.status import Status

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
US_ABBR = set(US_STATES.values())
# A booking page or social profile is not a business website: Hunter cannot search it.
PLATFORM_DOMAINS = ("instagram.", "facebook.", "linktr.ee", "square.site", "vagaro.", "booksy.", "mindbody", "google.", "glossgenius", "schedulicity", "visibook")
ON_ICP_NAME = re.compile(r"med ?spa|medical spa|aesthetic", re.I)
CHAIN_MIN = 3  # same brand this many times in one batch means a multi-location group, not an independent
CHAINS = [ln.strip().lower() for ln in (Path(__file__).parent / "data" / "chains.txt").read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def brand_key(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.split(r"\s[-–|]\s|:", name.lower())[0]).strip()


def _is_us(state: str | None) -> bool:
    # A missing state passes: the scrape is already restricted to countryCode us.
    if not state:
        return True
    s = state.strip()
    return s.lower() in US_STATES or s.upper() in US_ABBR


def clean_decision(lead: dict) -> str | None:
    """Reject reason, or None to keep. Batch-level rules (brand repeats, duplicate domains) live in run_clean."""
    if lead.get("closed"):
        return "closed"
    domain = lead.get("domain")
    if not domain or any(p in domain for p in PLATFORM_DOMAINS):
        return "no_website"
    if not _is_us(lead.get("state")):
        return "not_us"
    cats = lead.get("categories") or []
    name = lead.get("name") or ""
    if "Medical spa" not in cats and not ON_ICP_NAME.search(name):
        if "day spa" in name.lower() or any("day spa" in c.lower() for c in cats):
            return "day_spa"
        return "category"
    if any(c in name.lower() for c in CHAINS):
        return "chain"
    return None


def run_clean(db, batch_id: str) -> dict[str, int]:
    rows = (
        db.table("leads").select("id,name,domain,state,categories,closed,review_count")
        .eq("batch_id", batch_id).eq("status", Status.SCRAPED.value)
        .order("review_count", desc=True, nullsfirst=False).execute().data
    )
    if not rows:
        return {}
    seen = {
        r["domain"]
        for r in fetch_all(lambda: db.table("leads").select("domain").neq("status", Status.SCRAPED.value).neq("status", Status.REJECTED.value)
                           .not_.is_("domain", "null").order("id"))
    }
    brands = Counter(brand_key(r["name"]) for r in rows)
    by_reason: dict[str | None, list[str]] = {}
    for r in rows:
        reason = clean_decision(r)
        if reason is None and brands[brand_key(r["name"])] >= CHAIN_MIN:
            reason = "chain"
        if reason is None:
            if r["domain"] in seen:
                reason = "duplicate_domain"
            else:
                seen.add(r["domain"])
        by_reason.setdefault(reason, []).append(r["id"])
    counts: dict[str, int] = {}
    for reason, ids in by_reason.items():
        patch = {"status": Status.CLEANED.value, "reject_reason": None} if reason is None else {"status": Status.REJECTED.value, "reject_reason": reason}
        for i in range(0, len(ids), 100):
            db.table("leads").update(patch).in_("id", ids[i : i + 100]).execute()
        counts["cleaned" if reason is None else reason] = len(ids)
    return counts
