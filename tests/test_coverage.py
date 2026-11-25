from datetime import datetime, timedelta, timezone

import pytest

from gtm import coverage
from gtm.coverage import claim_tiles, load_metros, load_yield_stats, release_tile, state_code, yield_stats, reset_stale, seed_coverage, tile_scores
from gtm.db import get_db


def test_load_metros_reads_header_and_file_order(tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("metro_rank,metro,state,tile\n2,B,TX,b1\n1,A,CA,a1\n")
    assert load_metros(f) == [{"metro_rank": 2, "metro": "B", "state": "TX", "tile": "b1"},
                              {"metro_rank": 1, "metro": "A", "state": "CA", "tile": "a1"}]


# Test rows use metro "TEST" and negative seq so they sort before any real tile.
ROWS = [{"metro_rank": 1, "metro": "TEST", "state": "TX", "tile": f"t{i}"} for i in range(3)]


@pytest.fixture(autouse=True)
def plain_order(monkeypatch):
    monkeypatch.setattr(coverage, "setting", lambda k: False if k == "walk_yield_order" else None)


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


class FakeQ:
    """Just enough of the supabase query builder for claim_tiles on a list of coverage rows."""
    def __init__(self, rows):
        self.rows, self.f, self.upd, self.cnt, self.lim = rows, [], None, False, None

    def select(self, *a, count=None, **k): self.cnt = bool(count); return self
    def update(self, v): self.upd = v; return self
    def eq(self, c, v): self.f.append(lambda r: r[c] == v); return self
    def in_(self, c, v): self.f.append(lambda r: r[c] in v); return self
    def order(self, *a, **k): return self
    def limit(self, n): self.lim = n; return self
    def range(self, lo, hi): self.lim = (lo, hi); return self

    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self.f)]
        if self.upd is not None:
            for r in hit: r.update(self.upd)
            return type("R", (), {"data": hit, "count": None})
        hit.sort(key=lambda r: r["seq"])
        if isinstance(self.lim, tuple): hit = hit[self.lim[0]:self.lim[1] + 1]
        elif self.lim and not self.cnt: hit = hit[:self.lim]
        return type("R", (), {"data": hit, "count": len(hit) if self.cnt else None})


class FakeDB:
    def __init__(self, rows): self.rows = rows
    def table(self, name): return FakeQ(self.rows)


def _tiles(done=0):
    rows = [{"id": f"d{i}", "seq": -i - 1, "metro": "D", "state": "ZZ", "status": "done"} for i in range(done)]
    for i, (st, m) in enumerate([("AA", "m1"), ("AA", "m1"), ("BB", "m2"), ("BB", "m2"), ("CC", "m3")]):
        rows.append({"id": f"p{i}", "seq": i, "metro": m, "state": st, "status": "pending", "tile": f"t{i}"})
    return rows


def test_tile_scores_smooths_small_samples():
    s = tile_scores({"a": (1, 1), "b": (40, 20)}, 0.1)
    assert s["a"] < s["b"] and s["a"] > 0.1


def test_tile_scores_unknown_key_gets_global_rate():
    assert tile_scores({}, 0.07)["nope"] == 0.07


def test_claim_tiles_orders_by_score_then_seq_and_explores_every_third(monkeypatch):
    monkeypatch.setattr(coverage, "setting", lambda k: True)
    # BB is rich and well sampled, AA poor and well sampled, CC unsampled (kept < 40)
    monkeypatch.setattr(coverage, "load_yield_stats", lambda db: ({"AA": (100, 1), "BB": (100, 30), "CC": (5, 0)}, {}, 0.05))
    db = FakeDB(_tiles(done=2))  # 2 done -> this claim is the third: explore
    first = claim_tiles(db, 1)
    assert first[0]["id"] == "p4"  # lowest seq of a state with < 40 kept (CC)
    db = FakeDB(_tiles(done=0))  # claims 0,1 are by score, claim 2 explores
    got = [claim_tiles(db, 1)[0]["id"] for _ in range(3)]
    assert got == ["p2", "p3", "p4"]  # BB (seq order) first, then explore CC


def test_claim_tiles_with_setting_off_is_plain_seq(monkeypatch):
    monkeypatch.setattr(coverage, "load_yield_stats", lambda db: pytest.fail("not read"))
    got = claim_tiles(FakeDB(_tiles()), 3)
    assert [g["id"] for g in got] == ["p0", "p1", "p2"]


def test_explore_falls_back_to_lowest_seq_when_all_states_sampled(monkeypatch):
    monkeypatch.setattr(coverage, "setting", lambda k: True)
    monkeypatch.setattr(coverage, "load_yield_stats", lambda db: ({"AA": (50, 1), "BB": (50, 2), "CC": (50, 3)}, {}, 0.05))
    assert claim_tiles(FakeDB(_tiles(done=2)), 1)[0]["id"] == "p0"


def test_state_code_normalises_names_and_codes():
    assert [state_code(x) for x in ("TX", "texas", " Texas ", "New York", "ny", "District of Columbia", "dc", None, "", "Narnia")] == \
        ["TX", "TX", "TX", "NY", "NY", "DC", "DC", None, None, None]


def test_yield_stats_merge_spellings_and_count_all_leads():
    leads = [{"state": s, "status": st, "batch_id": b} for s, st, b in [
        ("TX", "enriched", None), ("Texas", "sent", None), ("Texas", "cleaned", None), ("NY", "no_buyer", None),
        ("New York", "drafted", "b1"), (None, "enriched", None), ("Narnia", "rejected", None)]]
    st, me, rate = yield_stats(leads, {"b1": {"metro": "NYC", "state": "NY"}}, {"NYC": 2})
    assert st == {"TX": (2, 2), "NY": (2, 1)} and me == {"NYC": (1, 1)}
    assert rate == 4 / 5  # 5 kept leads in all (the stateless one counts), 4 succeeded


def test_side_states_leave_yield_stats_unless_verified():
    def L(st, v=False): return {"state": "TX", "status": st, "batch_id": None, "owner_email": "a@b.co" if v else None, "email_verified": v}
    leads = [L("enriched"), L("enriched"), L("no_buyer")] + [L("suppressed")] * 3
    assert yield_stats(leads, {}, {})[0] == {"TX": (3, 2)}
    assert yield_stats(leads + [L("bounced", True), L("unsubscribed", True)], {}, {})[0] == {"TX": (5, 4)}


def test_high_yield_texas_wins_over_new_york(monkeypatch):
    monkeypatch.setattr(coverage, "setting", lambda k: True)
    monkeypatch.setattr(coverage, "load_yield_stats", lambda db: ({"NY": (124, 17), "TX": (100, 26), "CC": (50, 1)}, {}, 0.14))
    rows = [{"id": "ny", "seq": 0, "metro": "N", "state": "NY", "status": "pending"},
            {"id": "tx", "seq": 1, "metro": "H", "state": "TX", "status": "pending"}]
    assert claim_tiles(FakeDB(rows), 1)[0]["id"] == "tx"


@pytest.mark.db
def test_load_yield_stats_real_tables_read_only():
    st, me, g = load_yield_stats(get_db())
    assert 0 <= g <= 1 and st["TX"][1] / st["TX"][0] > st["NY"][1] / st["NY"][0]
