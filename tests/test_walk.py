import pytest

from gtm import coverage
from gtm.budget import BudgetExceeded
from gtm.cli import build_parser
from gtm.coverage import run_walk, seed_coverage
from gtm.db import get_db
from gtm.worker import ALLOWED

ROWS = [{"metro_rank": 1, "metro": "TEST", "state": "TX", "tile": f"t{i}"} for i in range(3)]
Q = ["q1", "q2", "q3"]


def _clean_up(d):
    ids = [r["scrape_batch_id"] for r in d.table("coverage").select("scrape_batch_id").eq("metro", "TEST").execute().data if r["scrape_batch_id"]]
    ids += [r["id"] for r in d.table("batches").select("id").eq("state", "TX").like("name", "t_ TX %").execute().data]
    d.table("leads").delete().like("place_id", "TEST_%").execute()
    d.table("coverage").delete().eq("metro", "TEST").execute()
    for b in set(ids):
        d.table("batches").delete().eq("id", b).execute()


@pytest.fixture
def db():
    d = get_db()
    _clean_up(d)
    seed_coverage(d, ROWS)
    for r in d.table("coverage").select("id,seq").eq("metro", "TEST").execute().data:
        d.table("coverage").update({"seq": r["seq"] - 1000}).eq("id", r["id"]).execute()
    yield d
    _clean_up(d)


def fake(counts):
    """run_actor returning counts[i] unique TEST_ places for call i; records the queries it saw."""
    seen = []

    def run(inp):
        i = len(seen)
        seen.append(inp)
        return [{"placeId": f"TEST_{i}_{j}", "title": "x", "state": "Texas"} for j in range(counts[i])], 0.01

    run.seen = seen
    return run


def walk(db, counts, tiles=1):
    f = fake(counts)
    return run_walk(db, f, tiles, queries=Q, max_places=10, escalate_at=0.9), f


def tile(db):
    return db.table("coverage").select("*").eq("metro", "TEST").order("seq").execute().data[0]


@pytest.mark.db
def test_unfilled_first_query_stops_the_tile(db):
    r, f = walk(db, [4])
    assert len(f.seen) == 1 and r["queries"] == 1 and r["saturated"] == 0
    t = tile(db)
    assert t["status"] == "done" and t["saturated"] is False


@pytest.mark.db
def test_filled_first_query_escalates_to_the_next(db):
    r, f = walk(db, [10, 3])
    assert len(f.seen) == 2 and r["queries"] == 2 and r["saturated"] == 0


@pytest.mark.db
def test_all_queries_filled_marks_saturated(db):
    r, f = walk(db, [10, 10, 10])
    assert len(f.seen) == 3 and r["saturated"] == 1 and tile(db)["saturated"] is True


@pytest.mark.db
def test_walk_marks_tile_done_and_records_counts(db):
    r, _ = walk(db, [10, 4])
    t = tile(db)
    assert t["status"] == "done" and t["places_found"] == 14 and t["new_leads"] == 14 and t["queries_run"] == 2
    assert t["scrape_batch_id"] and t["scraped_at"]
    assert db.table("batches").select("query").eq("id", t["scrape_batch_id"]).execute().data[0]["query"] == "q1, q2"
    assert r["new"] == 14 and r["tiles"] == 1


@pytest.mark.db
def test_walk_budget_block_releases_the_tile_and_creates_no_empty_batch(db, monkeypatch):
    def block(*a, **k):
        raise BudgetExceeded("cap")

    monkeypatch.setattr(coverage.budget, "require", block)
    before = len(db.table("batches").select("id").execute().data)
    with pytest.raises(BudgetExceeded):
        walk(db, [4])
    assert tile(db)["status"] == "pending"
    assert len(db.table("batches").select("id").execute().data) == before


@pytest.mark.db
def test_walk_failure_marks_failed_and_continues(db):
    calls = []

    def run(inp):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return [{"placeId": "TEST_ok", "title": "x", "state": "Texas"}], 0.01

    r = run_walk(db, run, 2, queries=Q, max_places=10, escalate_at=0.9)
    ts = db.table("coverage").select("status,error").eq("metro", "TEST").order("seq").execute().data
    assert ts[0]["status"] == "failed" and "boom" in ts[0]["error"] and ts[1]["status"] == "done"
    assert r["tiles"] == 1


def test_walk_is_job_runnable():
    assert "walk" in ALLOWED
    assert build_parser().parse_args(["walk", "--tiles", "1"]).tiles == 1
