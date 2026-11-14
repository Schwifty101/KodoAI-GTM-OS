import pytest

from gtm import places
from gtm.clean import clean_decision
from gtm.scrape import place_to_lead


def _place(pid="ChIJ1", name="Glow Medical Spa", types=None, primary="Medical spa", status="OPERATIONAL", site="https://glowmed.com/"):
    return {
        "id": pid, "displayName": {"text": name, "languageCode": "en"},
        "formattedAddress": "1 Main St, Sugar Land, TX 77478, USA",
        "addressComponents": [
            {"longText": "Sugar Land", "shortText": "Sugar Land", "types": ["locality", "political"]},
            {"longText": "Texas", "shortText": "TX", "types": ["administrative_area_level_1", "political"]},
        ],
        "websiteUri": site, "types": types or ["medical_spa", "health", "point_of_interest"],
        "primaryTypeDisplayName": {"text": primary, "languageCode": "en"},
        "rating": 4.8, "userRatingCount": 120, "businessStatus": status,
    }


def test_build_request_shape():
    assert places.build_request("med spa Sugar Land, TX") == {"textQuery": "med spa Sugar Land, TX", "languageCode": "en", "regionCode": "US", "pageSize": 20}
    assert places.build_request("q", "tok")["pageToken"] == "tok"


def test_field_mask_minimal():
    fields = set(places.FIELD_MASK.split(","))
    assert fields == {"nextPageToken", "places.id", "places.displayName", "places.formattedAddress", "places.addressComponents",
                      "places.websiteUri", "places.types", "places.primaryTypeDisplayName", "places.rating", "places.userRatingCount",
                      "places.businessStatus"}
    assert " " not in places.FIELD_MASK


def test_mapping_keeps_med_spa():
    item = places.to_apify_item(_place())
    assert (item["placeId"], item["title"], item["website"], item["city"], item["state"]) == ("ChIJ1", "Glow Medical Spa", "https://glowmed.com/", "Sugar Land", "TX")
    assert (item["totalScore"], item["reviewsCount"], item["permanentlyClosed"], item["temporarilyClosed"]) == (4.8, 120, False, False)
    assert "Medical spa" in item["categories"] and item["categoryName"] == "Medical spa"
    lead = place_to_lead(item, "b1")
    assert lead["tz"] == "America/Chicago" and clean_decision(lead) is None


def test_type_without_primary_still_maps():
    item = places.to_apify_item({**_place(), "primaryTypeDisplayName": None})
    assert "Medical spa" in item["categories"]


def test_rejects_day_spa_and_closed():
    day = place_to_lead(places.to_apify_item(_place("ChIJ2", "Serenity Day Spa", ["spa"], "Day spa")), "b")
    assert clean_decision(day) == "day_spa"
    shut = place_to_lead(places.to_apify_item(_place("ChIJ3", status="CLOSED_PERMANENTLY")), "b")
    assert clean_decision(shut) == "closed"
    temp = places.to_apify_item(_place("ChIJ4", status="CLOSED_TEMPORARILY"))
    assert temp["temporarilyClosed"] and not temp["permanentlyClosed"]


def test_missing_optional_fields():
    item = places.to_apify_item({"id": "ChIJ5", "displayName": {"text": "X"}})
    assert item["website"] is None and item["state"] is None and item["categories"] == []


def _pager(pages):
    calls = []

    def post(url, headers, json):
        calls.append((url, headers, json))
        return pages[len(calls) - 1]

    return post, calls


def test_paging_follows_token_and_caps():
    pages = [{"places": [_place(f"a{i}")], "nextPageToken": f"t{i}"} for i in range(5)]
    post, calls = _pager(pages)
    items, usd, n = places.search("q", post=post, max_pages=3)
    assert (len(items), n) == (3, 3) and usd == pytest.approx(3 * places.PRICE_PER_REQUEST_USD)
    assert "pageToken" not in calls[0][2] and calls[1][2]["pageToken"] == "t0"
    assert calls[0][0] == places.URL and calls[0][1]["X-Goog-FieldMask"] == places.FIELD_MASK


def test_paging_stops_without_token():
    post, calls = _pager([{"places": [_place("a")], "nextPageToken": "t"}, {"places": [_place("b")]}, {"places": [_place("c")]}])
    items, _, n = places.search("q", post=post)
    assert [i["placeId"] for i in items] == ["a", "b"] and n == 2


def test_empty_result():
    items, usd, n = places.search("q", post=_pager([{}])[0])
    assert (items, n) == ([], 1)


def test_cost_arithmetic():
    assert places.PRICE_PER_REQUEST_USD == pytest.approx(0.035)


def test_http_error_returns_collected():
    post, _ = _pager([{"places": [_place("a")], "nextPageToken": "t"}, {"error": {"code": 500, "status": "INTERNAL"}}])
    items, usd, n = places.search("q", post=post)
    assert len(items) == 1 and n == 2


@pytest.mark.parametrize("code", [403, 429])
def test_quota_errors_raise(code):
    post, _ = _pager([{"error": {"code": code, "status": "RESOURCE_EXHAUSTED"}}])
    with pytest.raises(places.PlacesError):
        places.search("q", post=post)
