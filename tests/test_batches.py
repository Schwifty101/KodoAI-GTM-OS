import pytest

from gtm.batches import assign_batches, plan_numbers
from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead


def test_plan_numbers():
    assert plan_numbers({}, 3) == [1, 1, 1]
    assert plan_numbers({1: 98}, 5) == [1, 1, 2, 2, 2]
    assert plan_numbers({1: 100}, 1) == [2]
    assert plan_numbers({1: 100, 2: 40}, 70) == [2] * 60 + [3] * 10
    assert plan_numbers({1: 50}, 0) == []


@pytest.fixture
def selected():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    items = [{"placeId": f"TEST_B{i}", "title": f"Spa {i}", "website": f"https://glowb{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(2)]
    db.table("leads").insert([{**place_to_lead(i, bid), "status": "selected"} for i in items]).execute()
    yield db
    db.table("leads").delete().like("place_id", "TEST_B%").execute()
    db.table("batches").delete().eq("id", bid).execute()


@pytest.mark.db
def test_assign_is_stable_on_rerun(selected):
    db = selected
    assert assign_batches(db) >= 2  # also numbers any real selected leads still waiting: that is the job
    first = db.table("leads").select("place_id,batch_no").like("place_id", "TEST_B%").order("place_id").execute().data
    assert all(r["batch_no"] for r in first)
    assert assign_batches(db) == 0
    assert db.table("leads").select("place_id,batch_no").like("place_id", "TEST_B%").order("place_id").execute().data == first
