import pytest

from gtm.clean import clean_decision, run_clean
from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead


def lead(**kw):
    base = {"place_id": "TEST_x", "name": "Glow Med Spa", "website": "https://glowmedspa.com", "domain": "glowmedspa.com",
            "state": "Texas", "category": "Medical spa", "categories": ["Medical spa"], "closed": False, "review_count": 50}
    return {**base, **kw}


def test_good_med_spa_is_kept():
    assert clean_decision(lead()) is None


def test_closed_is_rejected():
    assert clean_decision(lead(closed=True)) == "closed"


@pytest.mark.parametrize("website,domain", [(None, None), ("https://instagram.com/glow", "instagram.com"),
                                            ("https://glow.square.site", "glow.square.site"), ("https://www.vagaro.com/glow", "vagaro.com")])
def test_no_own_website_is_rejected(website, domain):
    assert clean_decision(lead(website=website, domain=domain)) == "no_website"


@pytest.mark.parametrize("domain", ["angelicaestheticsscheduling.as.me", "glow.acuityscheduling.com", "glow.squareup.com", "glow.setmore.com",
                                    "calendly.com", "glow.carrd.co", "glow.fresha.com", "styleseat.com", "glow.mindbodyonline.com"])
def test_booking_and_site_builder_tenants_are_rejected(domain):
    assert clean_decision(lead(domain=domain)) == "no_website"


def test_as_me_only_matches_as_a_domain_suffix():
    assert clean_decision(lead(domain="atlas.medical.com")) is None


@pytest.mark.parametrize("kw", [{"name": "Beyond Beauty Academy"}, {"categories": ["Medical spa", "Beauty school"]},
                                {"categories": ["Medical spa", "Training centre"]}, {"name": "Aesthetics Training Institute"}])
def test_training_school_is_rejected_as_not_a_clinic(kw):
    assert clean_decision(lead(**kw)) == "not_a_clinic"


def test_glow_medical_spa_still_passes():
    assert clean_decision(lead(name="Glow Medical Spa")) is None


def test_non_us_state_is_rejected_and_abbreviations_are_us():
    assert clean_decision(lead(state="Ontario")) == "not_us"
    assert clean_decision(lead(state="TX")) is None and clean_decision(lead(state="Texas")) is None


def test_med_spa_found_by_categories_list_when_primary_category_is_something_else():
    assert clean_decision(lead(category="Skin care clinic", categories=["Skin care clinic", "Medical spa"])) is None


def test_med_spa_found_by_name_when_google_files_it_as_spa():
    assert clean_decision(lead(name="EOV Med Spa", category="Health spa", categories=["Health spa"])) is None


def test_off_icp_category_is_rejected():
    assert clean_decision(lead(name="Clear Dermatology", category="Dermatologist", categories=["Dermatologist"])) == "category"
    assert clean_decision(lead(name="Neurogenx Foot Care Clinic", category="Medical clinic", categories=["Medical clinic"])) == "category"


def test_day_spa_is_rejected_but_med_spa_is_kept():
    assert clean_decision(lead(name="Serenity Day Spa", category="Day spa", categories=["Day spa"])) == "day_spa"
    assert clean_decision(lead(name="Glow Med Spa", category="Medical spa", categories=["Medical spa", "Day spa"])) is None


def test_known_chain_is_rejected():
    assert clean_decision(lead(name="LaserAway Sugar Land", categories=["Medical spa"])) == "chain"


def _item(pid, name, domain, reviews=10, **kw):
    return {"placeId": pid, "title": name, "website": f"https://{domain}", "categoryName": "Medical spa", "categories": ["Medical spa"],
            "state": "Texas", "reviewsCount": reviews, **kw}


@pytest.fixture
def two_batches():
    db = get_db()
    b1, b2 = new_batch(db, "A", "TX", ["x"]), new_batch(db, "B", "TX", ["x"])
    yield db, b1, b2
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    for b in (b1, b2):
        db.table("batches").delete().eq("id", b).execute()


def put(db, batch, items):
    db.table("leads").insert([place_to_lead(i, batch) for i in items]).execute()


def status(db, pid):
    r = db.table("leads").select("status,reject_reason").eq("place_id", pid).execute().data[0]
    return r["status"], r["reject_reason"]


@pytest.mark.db
def test_two_places_same_domain_keep_one_reject_the_other(two_batches):
    db, b1, _ = two_batches
    put(db, b1, [_item("TEST_a", "Glow Med Spa Katy", "glowmedspa.com", reviews=5), _item("TEST_b", "Glow Med Spa Sugar Land", "glowmedspa.com", reviews=90)])
    counts = run_clean(db, b1)
    assert status(db, "TEST_b") == ("cleaned", None)  # more reviews wins
    assert status(db, "TEST_a") == ("rejected", "duplicate_domain")
    assert counts["cleaned"] == 1 and counts["duplicate_domain"] == 1


@pytest.mark.db
def test_domain_already_cleaned_in_an_earlier_batch_is_a_duplicate(two_batches):
    db, b1, b2 = two_batches
    put(db, b1, [_item("TEST_a", "Glow Med Spa", "glowmedspa.com")])
    run_clean(db, b1)
    put(db, b2, [_item("TEST_b", "Glow Med Spa Annex", "glowmedspa.com")])
    run_clean(db, b2)
    assert status(db, "TEST_b") == ("rejected", "duplicate_domain")


@pytest.mark.db
def test_brand_repeated_three_times_in_a_batch_is_a_chain(two_batches):
    db, b1, _ = two_batches
    put(db, b1, [_item(f"TEST_{i}", f"ThrIVe Med Spa - {loc}", f"thrive{i}.com") for i, loc in enumerate(["Memorial", "Clear Lake", "Woodlands"])])
    counts = run_clean(db, b1)
    assert counts["chain"] == 3 and counts.get("cleaned", 0) == 0


@pytest.mark.db
def test_run_clean_only_touches_scraped_leads_and_is_rerunnable(two_batches):
    db, b1, _ = two_batches
    put(db, b1, [_item("TEST_a", "Glow Med Spa", "glowmedspa.com")])
    run_clean(db, b1)
    db.table("leads").update({"status": "enriched"}).eq("place_id", "TEST_a").execute()
    assert run_clean(db, b1) == {}  # nothing scraped left in the batch
    assert status(db, "TEST_a")[0] == "enriched"


def test_null_rating_and_reviews_do_not_change_the_decision():
    """Overture-sourced leads have no rating or review_count."""
    lead = {"name": "Glow Med Spa", "domain": "glowmed.com", "state": "TX", "category": "Medical spa", "categories": ["Medical spa"],
            "closed": False, "rating": None, "review_count": None}
    assert clean_decision(lead) is None
