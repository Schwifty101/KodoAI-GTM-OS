"""Google Places API (New) Text Search as a Maps source. Items come back in the Apify shape place_to_lead reads.
No budget or cost_log here: the caller wires budget.require and log_cost from the returned (usd, requests)."""

from __future__ import annotations

import httpx

from gtm.config import get_settings

URL = "https://places.googleapis.com/v1/places:searchText"
# Verified 2026-11-14 from https://developers.google.com/maps/billing-and-pricing/pricing and
# https://developers.google.com/maps/billing-and-pricing/sku-details/places.md.txt : a request is billed at the highest
# tier of any requested field. websiteUri/rating/userRatingCount are Enterprise; the rest are Pro or ID Only.
SKU = "Places API Text Search Enterprise"
PRICE_PER_1000_USD = 35.00  # 0-100k tier
PRICE_PER_REQUEST_USD = PRICE_PER_1000_USD / 1000
FREE_REQUESTS_PER_MONTH = 1000  # Enterprise SKU free cap (Pro is 5,000, but we request Enterprise fields)
PAGE_SIZE = 20  # documented max; at most 60 results across all pages per query (subject to change)
FIELD_MASK = ",".join([
    "nextPageToken", "places.id", "places.displayName", "places.formattedAddress", "places.addressComponents",
    "places.websiteUri", "places.types", "places.primaryTypeDisplayName", "places.rating", "places.userRatingCount",
    "places.businessStatus",
])
# Google type -> the readable name Apify gives, so clean_decision's "Medical spa" rule keeps working.
# Unlisted types are ignored (Google adds many generic ones: point_of_interest, health, establishment).
TYPE_NAMES = {
    "medical_spa": "Medical spa", "spa": "Spa", "skin_care_clinic": "Skin care clinic", "beauty_salon": "Beauty salon",
    "wellness_center": "Wellness center", "massage": "Massage therapist", "hair_salon": "Hair salon", "plastic_surgeon": "Plastic surgeon",
    "doctor": "Doctor", "medical_clinic": "Medical clinic", "dermatologist": "Dermatologist", "health": "Health",
}
QUOTA_CODES = (403, 429)


class PlacesError(RuntimeError):
    """Quota or permission failure (403/429): the walk should stop, not retry."""


def build_request(query: str, page_token: str | None = None) -> dict:
    body = {"textQuery": query, "languageCode": "en", "regionCode": "US", "pageSize": PAGE_SIZE}
    if page_token:
        body["pageToken"] = page_token
    return body


def _component(place: dict, kind: str, key: str) -> str | None:
    for c in place.get("addressComponents") or []:
        if kind in c.get("types", []):
            return c.get(key)
    return None


def to_apify_item(place: dict) -> dict:
    primary = (place.get("primaryTypeDisplayName") or {}).get("text")
    cats = [primary] if primary else []
    for t in place.get("types") or []:
        name = TYPE_NAMES.get(t)
        if name and name not in cats:
            cats.append(name)
    status = place.get("businessStatus")
    return {
        "placeId": place["id"],
        "title": (place.get("displayName") or {}).get("text"),
        "website": place.get("websiteUri"),
        "address": place.get("formattedAddress"),
        "city": _component(place, "locality", "longText"),
        "state": _component(place, "administrative_area_level_1", "shortText"),  # code, e.g. "TX"; lead_tz and _is_us accept codes
        "categoryName": cats[0] if cats else None,
        "categories": cats,
        "totalScore": place.get("rating"),
        "reviewsCount": place.get("userRatingCount"),
        "permanentlyClosed": status == "CLOSED_PERMANENTLY",
        "temporarilyClosed": status == "CLOSED_TEMPORARILY",
    }


def _http_post(url: str, headers: dict, json: dict) -> dict:
    h = {**headers, "X-Goog-Api-Key": get_settings().google_maps_api_key}
    try:
        r = httpx.post(url, headers=h, json=json, timeout=30)
    except httpx.HTTPError:
        return {"error": {"code": 0}}
    try:
        return r.json()
    except ValueError:
        return {"error": {"code": r.status_code}}


def search(query: str, post=None, max_pages: int = 3) -> tuple[list[dict], float, int]:
    """Returns (items in Apify shape, estimated usd, requests made). Other errors end paging and keep what was collected."""
    post = post or _http_post
    items: list[dict] = []
    requests = 0
    token = None
    for _ in range(max_pages):
        resp = post(URL, {"Content-Type": "application/json", "X-Goog-FieldMask": FIELD_MASK}, build_request(query, token))
        requests += 1
        err = resp.get("error")
        if err:
            if err.get("code") in QUOTA_CODES:
                raise PlacesError(f"Places API {err.get('code')} {err.get('status', '')}".strip())
            break  # ponytail: a 4xx/5xx mid-walk stops this query; failed requests may still be billed, estimate counts them
        items += [to_apify_item(p) for p in resp.get("places") or [] if p.get("id")]
        token = resp.get("nextPageToken")
        if not token:
            break
    return items, requests * PRICE_PER_REQUEST_USD, requests
