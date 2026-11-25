from scripts.yield_report import summarise


def L(status, state="TX", batch="b1", day="2026-11-20", owner=None):
    return {"status": status, "state": state, "batch_id": batch, "batch_created_at": day + "T10:00:00+00:00",
            "batch_query": "med spa", "owner_name": owner}


def test_zero_everything():
    s = summarise([], [], [])
    assert s["kept"] == 0 and s["enriched"] == 0 and s["rate"] is None
    assert s["states"] == {} and s["runs"] == [] and s["days"] == []


def test_state_with_only_rejected_leads():
    s = summarise([L("rejected", "FL"), L("scraped", "FL")], [], [])
    assert s["states"]["FL"] == {"kept": 0, "enriched": 0, "rate": None}


def test_counts_runs_and_named():
    s = summarise([L("rejected"), L("cleaned"), L("no_buyer", owner="A"), L("no_buyer"), L("sent", owner="B"), L("selected", owner="C")], [], [])
    assert s["kept"] == 4 and s["enriched"] == 2 and s["rate"] == 0.5
    r = s["runs"][0]
    assert (r["scraped"], r["kept"], r["named"], r["enriched"]) == (6, 4, 3, 2)


def test_days_group_and_guard_zero_spend():
    leads = [L("enriched", day="2026-11-20"), L("rejected", day="2026-11-20"), L("enriched", batch="b2", day="2026-11-21")]
    cost = [{"usd": 1.5, "created_at": "2026-11-20T01:00:00+00:00"}, {"usd": 0.5, "created_at": "2026-11-20T23:00:00+00:00"},
            {"usd": None, "created_at": "2026-11-21T01:00:00+00:00"}]
    jobs = [{"kind": "walk", "created_at": "2026-11-20T05:00:00+00:00"}, {"kind": "walk", "created_at": "2026-11-20T06:00:00+00:00"},
            {"kind": "walk", "created_at": "2026-11-21T05:00:00+00:00"}, {"kind": "enrich", "created_at": "2026-11-22T05:00:00+00:00"}]
    d = {x["day"]: x for x in summarise(leads, cost, jobs)["days"]}
    assert sorted(d) == ["2026-11-20", "2026-11-21"]
    assert d["2026-11-20"]["usd"] == 2.0 and d["2026-11-20"]["enriched"] == 1 and d["2026-11-20"]["per_usd"] == 0.5
    assert d["2026-11-21"]["usd"] == 0 and d["2026-11-21"]["per_usd"] is None
