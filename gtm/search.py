"""Web search through Serper (SERP_PROVIDER=serper). 2,500 free queries on signup (serper.dev); remaining balance unverified."""

from __future__ import annotations

import httpx

from gtm import budget
from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.hunter import OutOfCredits


_dead: set[str] = set()  # keys that answered "no credits" in this process; a restart retries them (ponytail: no balance polling)


def serper_post(url: str, post=None, **kw):
    """POST with the first Serper key that still has credits; a 400 'credits' answer retires that key and tries the next.
    Returns the last response (callers keep their own out-of-credits check); no keys at all sends the legacy single key."""
    post, keys = post or httpx.post, get_settings().serper_keys or [get_settings().serper_api_key]
    r = None
    for k in [k for k in keys if k not in _dead] or keys[-1:]:
        r = post(url, headers={"X-API-KEY": k}, **kw)
        if not (r.status_code == 400 and "credits" in str(r.json().get("message", "")).lower()):
            break
        _dead.add(k)
    return r


def serper_search(query: str, num: int = 5) -> list[dict]:
    budget.require("serper", 1)
    r = serper_post("https://google.serper.dev/search", json={"q": query, "num": num}, timeout=30)
    if r.status_code == 400 and "credits" in str(r.json().get("message", "")).lower():
        raise OutOfCredits("Serper has no credits left")
    r.raise_for_status()
    log_cost("serper", 1, None, note="search")
    return [{"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")} for o in r.json().get("organic", [])]


def serper_scrape(url: str) -> str | None:
    """Page text via Serper. Shape (third-party docs, official page not found, UNVERIFIED): POST https://scrape.serper.dev
    {"url": url} -> {"text", "markdown"?, "metadata", "credits"}; about 1 credit per page (UNVERIFIED, check on the first live call)."""
    budget.require("serper", 1)
    r = serper_post("https://scrape.serper.dev", json={"url": url}, timeout=60)
    r.raise_for_status()
    log_cost("serper", r.json().get("credits", 1), None, note="fetch-fallback:serper")
    return r.json().get("text") or None
