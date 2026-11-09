"""Web search through Serper (SERP_PROVIDER=serper). 2,500 free queries on signup (serper.dev); remaining balance unverified."""

from __future__ import annotations

import httpx

from gtm.config import get_settings
from gtm.costs import log_cost
from gtm.hunter import OutOfCredits


def serper_search(query: str, num: int = 5) -> list[dict]:
    r = httpx.post("https://google.serper.dev/search", headers={"X-API-KEY": get_settings().serper_api_key},
                   json={"q": query, "num": num}, timeout=30)
    if r.status_code == 400 and "credits" in str(r.json().get("message", "")).lower():
        raise OutOfCredits("Serper has no credits left")
    r.raise_for_status()
    log_cost("serper", 1, None, note="search")
    return [{"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")} for o in r.json().get("organic", [])]
