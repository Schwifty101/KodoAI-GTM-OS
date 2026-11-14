from datetime import datetime, timedelta, timezone

import pytest

from gtm.coverage import claim_tiles, load_metros, release_tile, reset_stale, seed_coverage
from gtm.db import get_db


def test_load_metros_reads_header_and_file_order(tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("metro_rank,metro,state,tile\n2,B,TX,b1\n1,A,CA,a1\n")
    assert load_metros(f) == [{"metro_rank": 2, "metro": "B", "state": "TX", "tile": "b1"},
                              {"metro_rank": 1, "metro": "A", "state": "CA", "tile": "a1"}]


# Test rows use metro "TEST" and negative seq so they sort before any real tile.
ROWS = [{"metro_rank": 1, "metro": "TEST", "state": "TX", "tile": f"t{i}"} for i in range(3)]


@pytest.fixture
def db():
    d = get_db()
    d.table("coverage").delete().eq("metro", "TEST").execute()
    yield d
    d.table("coverage").delete().eq("metro", "TEST").execute()


def seed(db):
    seed_coverage(db, ROWS)
    # seq = file position; shift below real rows so claims reach the test rows first
    for r in db.table("coverage").select("id,seq").eq("metro", "TEST").execute().data:
        db.table("coverage").update({"seq": r["seq"] - 1000}).eq("id", r["id"]).execute()


@pytest.mark.db
def test_seed_is_idempotent(db):
    assert seed_coverage(db, ROWS) == 3
    assert seed_coverage(db, ROWS) == 0


@pytest.mark.db
def test_claim_takes_lowest_seq_first_and_marks_running(db):
    seed(db)
    got = claim_tiles(db, 2)
    assert [g["tile"] for g in got] == ["t0", "t1"]
    assert all(g["status"] == "running" and g["started_at"] for g in got)


@pytest.mark.db
def test_claim_never_returns_the_same_tile_twice(db):
    seed(db)
    a, b = claim_tiles(db, 2), claim_tiles(db, 1)
    ids = [t["id"] for t in a + b]
    assert len(a) == 2 and len(b) == 1 and len(set(ids)) == 3


@pytest.mark.db
def test_release_returns_tile_to_pending(db):
    seed(db)
    t = claim_tiles(db, 1)[0]
    release_tile(db, t["id"])
    assert db.table("coverage").select("status").eq("id", t["id"]).execute().data[0]["status"] == "pending"


@pytest.mark.db
def test_reset_stale_returns_old_running_tile_to_pending(db):
    seed(db)
    old, fresh = claim_tiles(db, 2)
    db.table("coverage").update({"started_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()}).eq("id", old["id"]).execute()
    assert reset_stale(db) >= 1
    st = {r["id"]: r["status"] for r in db.table("coverage").select("id,status").eq("metro", "TEST").execute().data}
    assert st[old["id"]] == "pending" and st[fresh["id"]] == "running"
