"""Web search through Serper (SERP_PROVIDER=serper). 2,500 free queries on signup (serper.dev); remaining balance unverified."""

from __future__ import annotations

import httpx

from gtm import budget
from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.hunter import OutOfCredits


def serper_search(query: str, num: int = 5) -> list[dict]:
    budget.require("serper", 1)
    r = httpx.post("https://google.serper.dev/search", headers={"X-API-KEY": get_settings().serper_api_key},
                   json={"q": query, "num": num}, timeout=30)
    if r.status_code == 400 and "credits" in str(r.json().get("message", "")).lower():
        raise OutOfCredits("Serper has no credits left")
    r.raise_for_status()
    log_cost("serper", 1, None, note="search")
    return [{"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")} for o in r.json().get("organic", [])]


def serper_scrape(url: str) -> str | None:
    """Page text via Serper. Shape (third-party docs, official page not found, UNVERIFIED): POST https://scrape.serper.dev
    {"url": url} -> {"text", "markdown"?, "metadata", "credits"}; about 1 credit per page (UNVERIFIED, check on the first live call)."""
    budget.require("serper", 1)
    r = httpx.post("https://scrape.serper.dev", headers={"X-API-KEY": get_settings().serper_api_key}, json={"url": url}, timeout=60)
    r.raise_for_status()
    log_cost("serper", r.json().get("credits", 1), None, note="fetch-fallback:serper")
    return r.json().get("text") or None
