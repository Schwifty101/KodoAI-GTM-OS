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
        d.table("cost_log").delete().eq("batch_id", b).execute()  # no FK: scrape_city logs real spend rows
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


def _leads(db, batch):
    return db.table("leads").select("status").eq("batch_id", batch).execute().data


def _batch(db):
    return tile(db)["scrape_batch_id"] or db.table("batches").select("id").eq("state", "TX").like("name", "t_ TX %").execute().data[0]["id"]


@pytest.mark.db
def test_budget_block_after_query_one_cleans_leads_and_releases(db, monkeypatch):
    calls = []

    def req(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise BudgetExceeded("cap")

    monkeypatch.setattr(coverage.budget, "require", req)
    with pytest.raises(BudgetExceeded):
        walk(db, [10, 3])
    assert tile(db)["status"] == "pending"
    sts = {r["status"] for r in _leads(db, _batch(db))}
    assert sts and "scraped" not in sts


@pytest.mark.db
def test_exception_on_query_two_fails_tile_and_cleans_leads(db):
    n = []

    def run(inp):
        n.append(1)
        if len(n) == 2:
            raise RuntimeError("boom")
        return [{"placeId": f"TEST_{j}", "title": "x", "state": "Texas"} for j in range(10)], 0.01

    run_walk(db, run, 1, queries=Q, max_places=10, escalate_at=0.9)
    assert tile(db)["status"] == "failed"
    sts = {r["status"] for r in _leads(db, _batch(db))}
    assert sts and "scraped" not in sts


@pytest.mark.db
def test_budget_block_claims_one_tile_and_leaves_none_running(db):
    def run(inp):
        raise BudgetExceeded("cap")

    with pytest.raises(BudgetExceeded):
        run_walk(db, run, 3, queries=Q, max_places=10, escalate_at=0.9)
    assert [r["status"] for r in db.table("coverage").select("status").eq("metro", "TEST").execute().data] == ["pending"] * 3


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


@pytest.mark.db
def test_serper_provider_uses_own_gate_and_logs_credits(db, monkeypatch):
    gates = []
    monkeypatch.setattr("gtm.coverage.budget.require", lambda p, n=1, **k: gates.append((p, n)))
    f = fake([4])
    r = run_walk(db, f, 1, provider="serper")
    assert r["queries"] == 1 and gates == [("serper_maps", 3)]
    assert f.seen[0]["searchStringsArray"] == ["med spa"]  # fixed Serper wording list, not walk_queries
    b = tile(db)["scrape_batch_id"]
    rows = db.table("cost_log").select("provider,units,usd").eq("batch_id", b).execute().data
    assert rows == [{"provider": "serper_maps", "units": 3, "usd": None}]
