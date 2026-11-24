from datetime import datetime, timedelta, timezone

import pytest

from gtm import autopilot as ap
from gtm.autopilot import AutoState, BatchStage, decide
from gtm.db import get_db


def S(**kw):
    return AutoState(**{"on": True, **kw})


def B(i="b1", **kw):
    return BatchStage(batch_id=i, **kw)


def test_off_does_nothing():
    d = decide(S(on=False, batches=[B(scraped=5)]))
    assert d.state == "off" and d.enqueue is None


def test_open_job_enqueues_nothing():
    assert decide(S(open_job=True, batches=[B(scraped=5)])).enqueue is None


def test_spend_limit_pauses():
    d = decide(S(limit_usd=2.0, spent_usd=2.0, batches=[B(scraped=5)]))
    assert d.state == "paused: spend limit" and d.enqueue is None


def test_limit_zero_means_no_limit():
    assert decide(S(limit_usd=0, spent_usd=999.0, batches=[B(scraped=5)])).enqueue == ("clean", ["--batch", "b1"])


def test_credit_pause_stays_until_resume():
    d = decide(S(last_budget=("credit", "apify: out"), batches=[B(scraped=5)]))
    assert d.state == "paused: apify: out" and d.enqueue is None


def test_daily_cap_waits():
    d = decide(S(last_budget=("daily", "apify: daily cap"), batches=[B(scraped=5)]))
    assert d.state == "paused: daily cap" and d.enqueue is None


def test_daily_cap_retries_next_utc_day():
    now = datetime(2026, 11, 25, 1, tzinfo=timezone.utc)
    jobs = [{"kind": "clean", "status": "paused_budget", "error": "[daily] apify cap", "created_at": "2026-11-24T20:00:00+00:00", "finished_at": "2026-11-24T20:01:00+00:00", "payload": {}}]
    assert ap._last_budget(jobs, now) is None
    assert ap._last_budget(jobs, now.replace(day=24, hour=22)) == ("daily", "apify cap")


def test_error_without_prefix_is_credit():
    jobs = [{"status": "paused_budget", "error": "apify: broke", "finished_at": "2026-11-24T20:01:00+00:00"}]
    assert ap._last_budget(jobs, datetime(2026, 11, 25, tzinfo=timezone.utc)) == ("credit", "apify: broke")


def test_three_failures_pause():
    d = decide(S(recent_failures=3, batches=[B(scraped=5)]))
    assert d.state == "paused: errors" and d.enqueue is None


def test_stage_order_and_args():
    st = lambda **kw: decide(S(batches=[B(**kw)])).enqueue
    assert st(scraped=1, cleaned=1, enriched=1) == ("clean", ["--batch", "b1"])
    assert st(sheet_email_cleaned=1, cleaned=1) == ("verify-sheet", ["--batch", "b1", "--confirm"])
    assert st(cleaned=1, enriched=1) == ("enrich", ["--batch", "b1"])
    assert st(enriched=1, signalled=1) == ("signals", ["--batch", "b1"])
    assert st(signalled=1, approved_undrafted=1) == ("select", ["--batch", "b1"])
    assert st(approved_undrafted=1) == ("draft", ["--batch", "b1"])


def test_verify_skipped_when_allowance_spent():
    assert decide(S(verify_allowed=False, batches=[B(sheet_email_cleaned=1, cleaned=1)])).enqueue == ("enrich", ["--batch", "b1"])


def test_tried_pass_is_skipped_per_batch():
    s = S(tried={("clean", "b1")}, batches=[B("b1", scraped=1), B("b2", scraped=1)])
    assert decide(s).enqueue == ("clean", ["--batch", "b2"])


def test_select_that_leaves_signalled_leads_is_not_retried():
    d = decide(S(tried={("select", "b1")}, current_fill=100, batches=[B(signalled=3)]))
    assert d.enqueue is None


def test_walk_when_batch_not_full():
    d = decide(S(current_fill=30, in_flight=10, walk_tiles=3, tiles_left=True))
    assert d.state == "running" and d.enqueue == ("walk", ["--tiles", "3"])


def test_walk_not_queued_when_batch_full():
    d = decide(S(current_fill=60, in_flight=40, tiles_left=True))
    assert d.state == "waiting_approval" and d.enqueue is None


def test_waiting_approval_when_only_unapproved_selected_remain():
    d = decide(S(current_fill=10, unapproved_selected=100, tiles_left=True))
    assert d.state == "waiting_approval" and d.enqueue is None


def test_no_tiles_left_pauses():
    d = decide(S(current_fill=10, tiles_left=False))
    assert d.state == "paused: no tiles left" and d.enqueue is None


# --- database-backed: TEST_AP leads, TEST batch, own cost rows and jobs; settings are faked, never written ---
SINCE = datetime.now(timezone.utc) - timedelta(hours=1)
NOW = datetime.now(timezone.utc)


@pytest.fixture
def world(monkeypatch):
    db = get_db()
    cfg = {"autopilot_on": True, "autopilot_started_at": SINCE.isoformat(), "autopilot_limit_usd": 2.0, "autopilot_target": 100,
           "batch_base": {"3": 32}, "walk_tiles_per_run": 3, "autopilot_state": "off", "import_hunter_allowance_credits": 0.0}
    monkeypatch.setattr(ap, "setting", lambda key, db=None: cfg[key])
    monkeypatch.setattr(ap, "set_setting", lambda db, key, v: cfg.__setitem__(key, v))
    bid = db.table("batches").insert({"name": "TEST autopilot"}).execute().data[0]["id"]

    def wipe():
        db.table("jobs").delete().eq("payload->>test", "ap").execute()
        db.table("cost_log").delete().eq("provider", "TEST_ap").execute()
        db.table("leads").delete().like("place_id", "TEST_AP%").execute()

    wipe()
    try:
        yield db, bid, cfg
    finally:
        wipe()
        db.table("batches").delete().eq("id", bid).execute()


def lead(db, bid, n, status, **kw):
    db.table("leads").insert({"place_id": f"TEST_AP{n}", "name": f"TEST_AP{n}", "status": status, "batch_id": bid, **kw}).execute()


@pytest.mark.db
def test_load_state_counts_stages_and_spend(world):
    db, bid, cfg = world
    before = ap.load_state(db, NOW)
    lead(db, bid, 1, "scraped")
    lead(db, bid, 2, "cleaned", email_source="sheet", email_verified=False, owner_email="a@b.com")
    lead(db, bid, 3, "cleaned")
    lead(db, bid, 4, "enriched")
    lead(db, bid, 5, "signalled")
    lead(db, bid, 6, "selected", approved=True)
    lead(db, bid, 7, "selected", approved=False)
    lead(db, bid, 8, "selected", approved=False, batch_no=3)
    db.table("cost_log").insert([{"provider": "TEST_ap", "units": 1, "usd": 1.5, "created_at": NOW.isoformat()},{"provider": "TEST_ap", "units": 1, "usd": 9.0, "created_at": (SINCE - timedelta(hours=1)).isoformat()}]).execute()
    s = ap.load_state(db, NOW)
    b = next(x for x in s.batches if x.batch_id == bid)
    assert (b.scraped, b.sheet_email_cleaned, b.cleaned, b.enriched, b.signalled, b.approved_undrafted) == (1, 1, 2, 1, 1, 1)
    assert s.in_flight - before.in_flight == 4 and s.unapproved_selected - before.unapproved_selected == 2
    assert s.current_fill - before.current_fill == 1
    assert s.spent_usd - before.spent_usd == pytest.approx(1.5)
    assert s.on and s.limit_usd == 2.0 and s.target == 100


@pytest.mark.db
def test_load_state_reads_jobs(world):
    db, bid, cfg = world
    t = lambda sec: (NOW + timedelta(seconds=sec)).isoformat()
    job = lambda sec, status, kind="clean", error=None, **kw: {"kind": kind, "status": status, "error": error, "created_at": t(sec), "finished_at": t(sec), "payload": {"argv": ["--batch", bid], "test": "ap"}, **kw}
    db.table("jobs").insert([job(1, "done"), job(2, "paused_budget", error="[credit] apify: out of credit"), job(3, "done", kind="enrich"),
                             job(4, "failed", error="x"), job(5, "failed", error="x"), job(6, "failed", error="x")]).execute()
    s = ap.load_state(db, NOW + timedelta(seconds=10))
    assert {("clean", bid), ("enrich", bid)} <= s.tried
    assert s.last_budget == ("credit", "apify: out of credit")
    assert s.recent_failures == 3
    db.table("jobs").insert(job(7, "queued", kind="draft", run_after=t(86400 * 3650))).execute()  # far-future run_after: no worker claims it
    assert ap.load_state(db, NOW + timedelta(seconds=10)).open_job


@pytest.mark.db
def test_tick_enqueues_one_job_and_writes_state(world, monkeypatch):
    db, bid, cfg = world
    calls = []
    monkeypatch.setattr(ap, "enqueue", lambda db, kind, payload=None, **kw: calls.append((kind, payload)) or "job1")
    monkeypatch.setattr(ap, "load_state", lambda db, now: AutoState(on=True, batches=[BatchStage(bid, scraped=2)]))
    assert ap.autopilot_tick(db, NOW) == "job1"
    assert calls == [("clean", {"argv": ["--batch", bid]})] and cfg["autopilot_state"] == "running"
    monkeypatch.setattr(ap, "load_state", lambda db, now: AutoState(on=True, open_job=True, batches=[BatchStage(bid, scraped=2)]))
    assert ap.autopilot_tick(db, NOW) is None and len(calls) == 1
    cfg["autopilot_on"] = False
    assert ap.autopilot_tick(db, NOW) is None and cfg["autopilot_state"] == "off" and len(calls) == 1


def test_draft_again_when_more_approved_after_done_job():
    assert decide(S(tried={("draft", "b1", 2)}, batches=[B(approved_undrafted=5)])).enqueue == ("draft", ["--batch", "b1"])
    assert decide(S(batches=[B(approved_undrafted=5)])).n == 5


def test_draft_not_repeated_when_count_unchanged():
    assert decide(S(tried={("draft", "b1", 2)}, current_fill=100, batches=[B(approved_undrafted=2)])).enqueue is None


def test_tick_puts_draft_count_in_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(ap, "enqueue", lambda db, kind, payload=None, **kw: calls.append((kind, payload)) or "j")
    monkeypatch.setattr(ap, "load_state", lambda db, now: AutoState(on=True, batches=[B(approved_undrafted=4)]))
    monkeypatch.setattr(ap, "setting", lambda key, db=None: {"autopilot_on": True, "autopilot_state": "running"}[key])
    monkeypatch.setattr(ap, "set_setting", lambda db, key, v: None)
    assert ap.autopilot_tick(None, NOW) == "j" and calls == [("draft", {"argv": ["--batch", "b1"], "n": 4})]


@pytest.mark.db
def test_skipped_signalled_leads_are_not_counted(world):
    db, bid, cfg = world
    s0 = ap.load_state(db, NOW)
    for i in (1, 2, 3):
        lead(db, bid, i, "signalled", reject_reason="no_handoff")
    lead(db, bid, 4, "signalled")
    s = ap.load_state(db, NOW)
    assert next(x for x in s.batches if x.batch_id == bid).signalled == 1
    assert s.in_flight - s0.in_flight == 1


def J(kind, status="done", out="", error=None, argv=None, n=None):
    return {"kind": kind, "status": status, "error": error, "payload": {"argv": argv if argv is not None else [], **({"n": n} if n else {})}, "result": {"output": out}}


def test_walk_dud_counts_consecutive_newest_empty_walks():
    dud, ok = J("walk", out="{'tiles': 0, 'queries': 0}\n"), J("walk", out="{'tiles': 2, 'new': 5}\n")
    assert ap._walk_dud([dud, J("clean", argv=["--batch", "b"]), dud, ok, dud]) == 2
    assert ap._walk_dud([ok, dud, dud, dud]) == 0


def test_three_dud_walks_pause_before_another_walk():
    d = decide(S(walk_dud=3, current_fill=10, tiles_left=True))
    assert d.state == "paused: walk found nothing (3 in a row)" and d.enqueue is None
    assert decide(S(walk_dud=2, current_fill=10, tiles_left=True)).enqueue[0] == "walk"


def test_out_of_credits_in_newest_pass_output_pauses():
    assert ap._out_of_credits([J("enrich", out="{'enriched': 1, 'out_of_credits': 4}"), J("signals", out="{}")])
    assert not ap._out_of_credits([J("enrich", out="{'out_of_credits': 0}")])
    assert not ap._out_of_credits([J("enrich", out="{'enriched': 2}"), J("enrich", out="{'out_of_credits': 4}")])  # the newest enrich was fine
    d = decide(S(out_of_credits=True, batches=[B(scraped=5)]))
    assert d.state == "paused: out of credits" and d.enqueue is None


def test_user_cancelled_job_is_tried_but_interrupted_one_reruns():
    jobs = [J("clean", "cancelled", error="cancelled by owner", argv=["--batch", "b1"]), J("enrich", "cancelled", error="interrupted", argv=["--batch", "b1"])]
    assert ap._tried(jobs) == {("clean", "b1")}


def test_full_batch_rule_follows_target():
    assert ap._fill(60, 50) == 10 and ap._fill(50, 50) == 0 and ap._fill(60, 100) == 60 and ap._fill(100, 100) == 0
    assert decide(S(target=50, current_fill=ap._fill(60, 50), tiles_left=True)).enqueue[0] == "walk"


def test_open_job_returns_before_any_scan(world, monkeypatch):
    db, bid, cfg = world
    db.table("jobs").insert({"kind": "draft", "status": "queued", "run_after": (NOW + timedelta(days=3650)).isoformat(), "payload": {"argv": ["--batch", bid], "test": "ap"}}).execute()
    monkeypatch.setattr(ap, "fetch_all", lambda build: pytest.fail("scanned despite an open job"))
    s = ap.load_state(db, NOW)
    assert s.open_job and s.batches == []


def test_fresh_read_drops_the_cached_value_first(monkeypatch):
    from gtm import settings_store

    settings_store._cache["autopilot_on"] = (1e18, True)
    monkeypatch.setattr(ap, "setting", lambda key, db=None: "autopilot_on" in settings_store._cache)  # True would mean a cached read
    assert ap._fresh("autopilot_on", None) is False


@pytest.mark.db
def test_load_state_records_draft_count_from_done_job(world):
    db, bid, cfg = world
    db.table("jobs").insert({"kind": "draft", "status": "done", "created_at": NOW.isoformat(), "payload": {"argv": ["--batch", bid], "n": 2, "test": "ap"}}).execute()
    assert ("draft", bid, 2) in ap.load_state(db, NOW).tried
