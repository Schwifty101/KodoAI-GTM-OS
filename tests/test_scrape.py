import pytest

from gtm.apify import choose_key
from gtm.db import get_db
from gtm.scrape import DEFAULT_QUERIES, SCRAPE_COLUMNS, new_batch, place_to_lead, scrape_city, scrape_input

ITEM = {
    "placeId": "TEST_p1", "title": "Glow Med Spa", "website": "https://www.glowmedspa.com/about",
    "address": "1 Main St, Sugar Land, TX 77478", "city": "Sugar Land", "state": "Texas",
    "categoryName": "Medical spa", "categories": ["Medical spa", "Skin care clinic"],
    "totalScore": 4.6, "reviewsCount": 120, "permanentlyClosed": False, "temporarilyClosed": False,
    "phone": "+1 555 0100", "imageUrl": "x", "additionalInfo": {"junk": True},
}


def test_place_to_lead_keeps_only_needed_fields():
    lead = place_to_lead(ITEM, "batch-1")
    assert set(lead) == SCRAPE_COLUMNS
    assert lead["place_id"] == "TEST_p1" and lead["name"] == "Glow Med Spa"
    assert lead["domain"] == "glowmedspa.com"  # no scheme, no www, no path
    assert lead["categories"] == ["Medical spa", "Skin care clinic"] and lead["category"] == "Medical spa"
    assert (lead["rating"], lead["review_count"]) == (4.6, 120)
    assert lead["status"] == "scraped" and lead["batch_id"] == "batch-1"


@pytest.mark.parametrize("flags", [{"permanentlyClosed": True}, {"temporarilyClosed": True}])
def test_closed_when_permanently_or_temporarily_closed(flags):
    assert place_to_lead({**ITEM, **flags}, "b")["closed"] is True
    assert place_to_lead(ITEM, "b")["closed"] is False


def test_item_without_website_has_no_domain():
    lead = place_to_lead({**ITEM, "website": None}, "b")
    assert lead["website"] is None and lead["domain"] is None


def test_scrape_input_uses_defaults_and_no_category_filter():
    inp = scrape_input("Sugar Land", "TX", DEFAULT_QUERIES, 40)
    assert DEFAULT_QUERIES == ["med spa", "aesthetics clinic", "botox"]
    assert inp["searchStringsArray"] == DEFAULT_QUERIES
    assert inp["locationQuery"] == "Sugar Land, TX, USA" and inp["countryCode"] == "us"
    assert inp["website"] == "withWebsite" and inp["maxCrawledPlacesPerSearch"] == 40
    assert "categoryFilterWords" not in inp


def test_choose_key_picks_most_remaining_and_refuses_below_apify_minimum():
    assert choose_key({"k1": 4.9, "k2": 9.1}) == "k2"
    with pytest.raises(RuntimeError):
        choose_key({"k1": 0.4, "k2": 0.2})  # Apify rejects a cap below $0.50


@pytest.fixture
def batch():
    db = get_db()
    bid = new_batch(db, "Sugar Land", "TX", ["med spa"])
    yield bid
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("cost_log").delete().eq("batch_id", bid).execute()
    db.table("batches").delete().eq("id", bid).execute()


def fake_actor(items, usd=0.005):
    seen = []

    def run(run_input):
        seen.append(run_input)
        return items, usd

    run.seen = seen
    return run


@pytest.mark.db
def test_known_place_id_is_skipped_not_duplicated(batch):
    db = get_db()
    actor = fake_actor([ITEM, ITEM])  # the same place twice in one run counts once
    assert scrape_city(db, actor, "Sugar Land", "TX", ["med spa"], batch) == (1, 0)
    assert scrape_city(db, actor, "Sugar Land", "TX", ["med spa"], batch) == (0, 1)
    assert len(db.table("leads").select("id").eq("place_id", "TEST_p1").execute().data) == 1


@pytest.mark.db
def test_known_place_is_never_requeued_for_enrichment(batch):
    db = get_db()
    actor = fake_actor([ITEM])
    scrape_city(db, actor, "Sugar Land", "TX", ["med spa"], batch)
    db.table("leads").update({"status": "cleaned"}).eq("place_id", "TEST_p1").execute()
    scrape_city(db, actor, "Sugar Land", "TX", ["med spa"], batch)
    assert db.table("leads").select("status").eq("place_id", "TEST_p1").execute().data[0]["status"] == "cleaned"


@pytest.mark.db
def test_scrape_logs_apify_cost_against_the_batch(batch):
    db = get_db()
    scrape_city(db, fake_actor([ITEM], usd=0.0123), "Sugar Land", "TX", ["med spa"], batch)
    rows = db.table("cost_log").select("*").eq("batch_id", batch).execute().data
    assert [(r["provider"], float(r["units"]), float(r["usd"])) for r in rows] == [("apify", 1.0, 0.0123)]
