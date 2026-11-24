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


def _is_new(build):
    _is_new.calls += 1  # candidate query first, counts query second
    return _is_new.calls % 2 == 1


_is_new.calls = 0


def _run(monkeypatch, base, n_new):
    from unittest.mock import MagicMock

    from gtm import batches

    _is_new.calls = 0
    new = [{"id": f"n{i}"} for i in range(n_new)]
    monkeypatch.setattr(batches, "setting", lambda k, db=None: base)
    monkeypatch.setattr(batches, "fetch_all", lambda build: new if _is_new(build) else [])
    db = MagicMock()
    assert batches.assign_batches(db) == n_new
    return [c.args[0]["batch_no"] for c in db.table.return_value.update.call_args_list]


def test_assign_counts_batch_base(monkeypatch):
    assert _run(monkeypatch, {"3": 32}, 3) == [3, 3, 3]


def test_select_crossing_100_rolls_into_next_batch_with_base(monkeypatch):
    assert _run(monkeypatch, {"3": 98}, 5) == [3, 3, 4, 4, 4]


@pytest.mark.db
def test_renumber_dry_run_changes_nothing_and_confirm_moves_only_selected(selected):
    from gtm.batches import renumber

    db, ids, other = selected
    db.table("leads").update({"batch_no": 9001}).in_("id", [ids[0], other]).execute()
    db.table("leads").update({"batch_no": 9001, "status": "drafted"}).eq("id", ids[1]).execute()
    state = lambda: {r["id"]: r["batch_no"] for r in db.table("leads").select("id,batch_no").in_("id", ids + [other]).execute().data}
    before = state()
    assert renumber(db, 9001, 9002) == 2 and state() == before
    assert renumber(db, 9001, 9002, confirm=True) == 2
    after = state()
    assert after[ids[0]] == after[other] == 9002 and after[ids[1]] == 9001
