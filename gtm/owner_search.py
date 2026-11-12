"""Find an owner by searching `owner of <domain>`. The model reads the results; code refuses anything it cannot see in them."""

from __future__ import annotations

import re

from gtm.buyer import is_decision_maker
from gtm.sitescrape import _clean_name

GENERIC = {"med", "medical", "spa", "medspa", "aesthetics", "aesthetic", "clinic", "wellness", "skin", "skincare", "laser", "the", "of",
           "and", "center", "centre", "institute", "beauty", "cosmetic", "studio", "lounge", "body", "health", "care", "md", "dr", "llc"}
SYSTEM = (
    "You read Google search results about one med spa and find its owner. Use only the text given. "
    'Reply with JSON {"name": str|null, "title": str|null, "url": str|null}. name is a person\'s full name copied exactly from a '
    "result's title or snippet; title is their role as written there; url is that result's link. If no result clearly names an owner, "
    "founder, CEO or president of THIS business (not a similarly named one), return all nulls."
)


def _about_business(text: str, business: dict) -> bool:
    low = text.lower()
    words = set(re.findall(r"[a-z0-9]+", low))
    city = set(re.findall(r"[a-z0-9]+", (business.get("city") or "").lower()))
    distinct = set(re.findall(r"[a-z0-9]+", business["name"].lower())) - GENERIC - city
    if distinct & words:
        return True
    stem = business["domain"].split(".")[0].lower()
    if stem and stem in re.sub(r"[^a-z0-9]", "", low):
        return True
    full = re.sub(r"^the ", "", re.sub(r"[^a-z0-9 ]", "", business["name"].lower())).strip()
    return bool(full) and full in re.sub(r"[^a-z0-9 ]", "", low)


def validate_owner(ans: dict, results: list[dict], business: dict) -> dict | None:
    name, title, url = ans.get("name"), ans.get("title"), ans.get("url")
    if not (name and title and url):
        return None
    res = next((r for r in results if r["link"] == url), None)
    if not res:
        return None
    text = f"{res['title']} {res.get('snippet', '')}"
    if name.lower() not in text.lower() or not is_decision_maker(title) or not _about_business(text + " " + url, business):
        return None
    n = _clean_name(name)
    if not n:
        return None
    return {"first_name": n[0], "last_name": n[1], "position": title, "url": url}


def search_owner_finder(pool, search, llm):
    """Finder for run_enrich: one search, one model read, then Hunter Email Finder (1 credit only if it finds an email)."""

    def find(lead: dict) -> list[dict]:
        results = search(f"owner of {lead['domain']}")
        if not results:
            return []
        listing = "\n".join(f"{i + 1}. {r['title']} | {r['link']} | {r['snippet']}" for i, r in enumerate(results))
        prompt = f"Business: {lead['name']} ({lead['domain']}), {lead.get('city') or ''}\n\nResults:\n{listing}"
        owner = validate_owner(llm(SYSTEM, prompt), results, lead)
        if not owner:
            return []
        c = pool.email_finder(lead["domain"], owner["first_name"], owner["last_name"])
        if not c:  # keep the validated name: later finders (and the lead row) can still use it
            return [{"email": None, "first_name": owner["first_name"], "last_name": owner["last_name"], "position": owner["position"],
                     "source": "search", "evidence_url": owner["url"]}]
        return [{**c, "position": owner["position"], "source": "search+hunter", "evidence_url": owner["url"]}]

    return find
