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
    try:
        items = [{"placeId": f"TEST_B{i}", "title": f"Spa {i}", "website": f"https://glowb{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(3)]
        rows = db.table("leads").insert([{**place_to_lead(i, bid), "status": "selected"} for i in items]).execute().data
        yield db, [r["id"] for r in rows[:2]], rows[2]["id"]
    finally:
        db.table("leads").delete().like("place_id", "TEST_B%").execute()
        db.table("batches").delete().eq("id", bid).execute()


@pytest.mark.db
def test_assign_is_stable_on_rerun(selected):
    db, ids, other = selected
    q = lambda: db.table("leads").select("place_id,batch_no").like("place_id", "TEST_B%").in_("id", ids).order("place_id").execute().data
    assert assign_batches(db, ids) == 2
    first = q()
    assert all(r["batch_no"] for r in first)
    assert assign_batches(db, ids) == 0
    assert q() == first
    assert db.table("leads").select("batch_no").eq("id", other).execute().data[0]["batch_no"] is None
