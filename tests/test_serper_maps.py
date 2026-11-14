import pytest

from gtm import serper_maps as sm
from gtm.budget import BudgetExceeded
from gtm.clean import clean_decision
from gtm.scrape import place_to_lead

PLACE = {"placeId": "ChIJabc", "title": "Glow Medical Spa", "website": "https://glowmed.com/", "type": "Medical spa",
         "types": ["Medical spa", "Skin care clinic"], "rating": 4.8, "ratingCount": 120,
         "address": "1 Main St, Sugar Land, TX 77478"}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status
    def json(self):
        return self.data
    def raise_for_status(self):
        assert self.status_code < 400


@pytest.mark.parametrize("addr,want", [
    ("1 Main St, Sugar Land, TX 77478", ("Sugar Land", "TX")),
    ("350 5th Ave Suite 1, New York, NY 10118, United States", ("New York", "NY")),
    ("Cary, NC 27511", (None, None)),  # no street part: unparsed rather than guessed
    (None, (None, None)),
])
def test_parse_city_state(addr, want):
    assert sm.parse_city_state(addr) == want


def test_mapping_keeps_med_spa_through_clean():
    item = sm.to_apify_item(PLACE)
    assert (item["placeId"], item["city"], item["state"], item["totalScore"], item["reviewsCount"]) == ("ChIJabc", "Sugar Land", "TX", 4.8, 120)
    assert item["categories"] == ["Medical spa", "Skin care clinic"] and item["categoryName"] == "Medical spa"
    lead = place_to_lead(item, "b")
    assert lead["closed"] is False and lead["tz"] == "America/Chicago"
    assert clean_decision(lead) is None
    assert clean_decision(place_to_lead(sm.to_apify_item({**PLACE, "address": "1 Rue X, Toronto, ON 12345"}), "b")) == "not_us"


def test_drops_no_website_and_no_placeid():
    assert sm.to_apify_item({**PLACE, "website": None}) is None
    assert sm.to_apify_item({**PLACE, "placeId": None}) is None


def test_one_call_no_paging():
    sent = []
    def post(url, **kw):
        sent.append(kw["json"])
        return Resp({"places": [PLACE, {**PLACE, "placeId": "x", "website": None}]})
    assert len(sm.serper_maps("med spa Cary, NC, USA", post=post)) == 1
    assert sent == [{"q": "med spa Cary, NC, USA"}]  # no page, no ll


def test_run_serper_builds_tile_query(monkeypatch):
    seen = []
    monkeypatch.setattr(sm, "serper_maps", lambda q: seen.append(q) or [])
    from gtm.scrape import scrape_input
    assert sm.run_serper(scrape_input("Cary", "NC", ["botox"], 20)) == ([], None)
    assert seen == ["botox Cary, NC, USA"]


def test_over_cap_raises_and_makes_no_call(monkeypatch):
    monkeypatch.setattr("gtm.budget._cost_rows", lambda db, provider, since: [{"units": 299, "usd": None}])
    def post(*a, **k):
        raise AssertionError("HTTP call made over cap")
    with pytest.raises(BudgetExceeded):
        sm.serper_maps("q", post=post)


def test_out_of_credits():
    with pytest.raises(sm.OutOfCredits):
        sm.serper_maps("q", post=lambda *a, **k: Resp({"message": "Not enough credits"}, 400))
