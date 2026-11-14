"""Scrape pass: Apify Google Maps results become `scraped` leads. Known place IDs are never touched."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from gtm.costs import log_cost
from gtm.status import Status
from gtm.tz import lead_tz

DEFAULT_QUERIES = ["med spa", "aesthetics clinic", "botox"]  # measured, docs/spikes/apify.md A2
SCRAPE_COLUMNS = {
    "place_id", "name", "website", "domain", "address", "city", "state", "category", "categories",
    "closed", "rating", "review_count", "status", "batch_id", "tz",
}


def _domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "//" in website else "//" + website).netloc.lower()
    return host.removeprefix("www.") or None


def place_to_lead(item: dict, batch_id: str) -> dict:
    return {
        "place_id": item["placeId"],
        "name": item["title"],
        "website": item.get("website"),
        "domain": _domain(item.get("website")),
        "address": item.get("address"),
        "city": item.get("city"),
        "state": item.get("state"),
        "category": item.get("categoryName"),
        "categories": item.get("categories") or [],
        "closed": bool(item.get("permanentlyClosed") or item.get("temporarilyClosed")),
        "rating": item.get("totalScore"),
        "review_count": item.get("reviewsCount"),
        "status": Status.SCRAPED.value,
        "batch_id": batch_id,
        "tz": lead_tz(item.get("state"), item.get("city")),
    }


def scrape_input(city: str, state: str, queries: list[str], max_places: int) -> dict:
    return {
        "searchStringsArray": queries,
        "locationQuery": f"{city}, {state}, USA",
        "countryCode": "us",
        "language": "en",
        "website": "withWebsite",
        "maxCrawledPlacesPerSearch": max_places,
    }


def new_batch(db, city: str, state: str, queries: list[str]) -> str:
    row = {"name": f"{city} {state} {date.today()}", "city": city, "state": state, "query": ", ".join(queries)}
    return db.table("batches").insert(row).execute().data[0]["id"]


def scrape_city(db, run_actor, city: str, state: str, queries: list[str], batch_id: str, max_places: int = 40, provider: str = "apify") -> tuple[int, int]:
    """Returns (new, already_known). run_actor(run_input) -> (items, usd)."""
    items, usd = run_actor(scrape_input(city, state, queries, max_places))
    if provider == "serper":
        from gtm.serper_maps import CREDITS_PER_CALL  # local: serper_maps imports budget, which imports the db

        log_cost("serper_maps", CREDITS_PER_CALL, None, batch_id=batch_id, note=queries[0][:80])
    else:
        log_cost("apify", len(items), usd, batch_id=batch_id)
    leads = {}
    for it in items:
        if it.get("placeId") and it["placeId"] not in leads:
            leads[it["placeId"]] = place_to_lead(it, batch_id)
    ids = list(leads)
    known: set[str] = set()
    for i in range(0, len(ids), 100):
        known |= {r["place_id"] for r in db.table("leads").select("place_id").in_("place_id", ids[i : i + 100]).execute().data}
    fresh = [lead for pid, lead in leads.items() if pid not in known]
    if fresh:
        db.table("leads").upsert(fresh, on_conflict="place_id", ignore_duplicates=True).execute()
    return len(fresh), len(known)
