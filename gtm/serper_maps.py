"""Serper /maps as a scrape provider. A call returns the first 20 places for a query-text tile (no `ll`, no paging:
page 2 needs `ll`, and `ll` bias is weak). Items come back in the Apify shape place_to_lead reads.
Spec: docs/NEXT-source-pilot.md. USD per Serper credit is UNVERIFIED, so cost_log gets credits only (usd None)."""

from __future__ import annotations

import re

import httpx

from gtm import budget
from gtm.config import get_settings

URL = "https://google.serper.dev/maps"
CREDITS_PER_CALL = 3
PLACES_PER_CALL = 20
QUERIES = ["med spa", "aesthetics clinic", "botox", "medical spa", "laser hair removal"]  # measured on Manhattan, maps_sources.md
_CITY_STATE = re.compile(r",\s*([^,]+),\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?(?:,|$)")


class OutOfCredits(RuntimeError):
    pass


def parse_city_state(address: str | None) -> tuple[str | None, str | None]:
    m = _CITY_STATE.search(address or "")
    return (m.group(1).strip(), m.group(2)) if m else (None, None)


def to_apify_item(place: dict) -> dict | None:
    """None when the place has no placeId or no website (replaces Apify's withWebsite filter).
    Known gap: Serper shows no closed flag, so permanentlyClosed stays unset."""
    if not place.get("placeId") or not place.get("website"):
        return None
    cats = list(dict.fromkeys([*(place.get("types") or []), *([place["type"]] if place.get("type") else [])]))
    city, state = parse_city_state(place.get("address"))
    return {
        "placeId": place["placeId"], "title": place.get("title"), "website": place["website"], "address": place.get("address"),
        "city": city, "state": state, "categoryName": cats[0] if cats else None, "categories": cats,
        "totalScore": place.get("rating"), "reviewsCount": place.get("ratingCount"),
    }


def serper_maps(query: str, post=None) -> list[dict]:
    """One call, items in Apify shape. Budget gate here; the caller logs CREDITS_PER_CALL to cost_log (it knows the batch)."""
    budget.require("serper_maps", CREDITS_PER_CALL)
    post = post or httpx.post
    r = post(URL, headers={"X-API-KEY": get_settings().serper_api_key}, json={"q": query}, timeout=30)
    if r.status_code == 400 and "credits" in str(r.json().get("message", "")).lower():
        raise OutOfCredits("Serper has no credits left")
    r.raise_for_status()
    return [i for p in r.json().get("places") or [] if (i := to_apify_item(p))]


def run_serper(inp: dict) -> tuple[list[dict], None]:
    """run_actor adapter for scrape_city/run_walk: tile text from the Apify-shaped input (one query per call)."""
    return serper_maps(f"{inp['searchStringsArray'][0]} {inp['locationQuery']}"), None
