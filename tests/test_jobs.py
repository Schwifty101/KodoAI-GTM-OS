from datetime import datetime, timedelta, timezone

import pytest

from gtm.db import get_db
from tests.conftest import real_jobs
from gtm.jobs import claim, enqueue, finish, requeue_stale

pytestmark = pytest.mark.db
db = get_db()
T = {"test": 1}


@pytest.fixture(autouse=True)
def clean(no_real_jobs):
    def wipe():
        db.table("jobs").delete().eq("payload->>test", "1").execute()
    wipe()
    yield
    wipe()


def test_enqueue_then_claim_returns_the_job_running():
    jid = enqueue(db, "clean", T)
    j = claim(db)
    assert j["id"] == jid and j["status"] == "running" and j["started_at"]


def test_claim_is_atomic_second_claim_gets_nothing():
    enqueue(db, "clean", T)
    assert [x for x in (claim(db), claim(db)) if x] and claim(db) is None


def test_future_run_after_is_not_claimed():
    enqueue(db, "clean", T, run_after=datetime.now(timezone.utc) + timedelta(hours=1))
    assert claim(db) is None


def test_requeue_stale_returns_old_running_job_to_queue():
    old, new = enqueue(db, "clean", T), enqueue(db, "clean", T)
    two_h = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.table("jobs").update({"status": "running", "started_at": two_h}).eq("id", old).execute()
    db.table("jobs").update({"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}).eq("id", new).execute()
    assert requeue_stale(db) == 1
    st = {r["id"]: r["status"] for r in db.table("jobs").select("id,status").in_("id", [old, new]).execute().data}
    assert st == {old: "queued", new: "running"}


def test_requeue_stale_fails_jobs_after_three_attempts():
    spent, fresh = enqueue(db, "clean", T), enqueue(db, "clean", T)
    two_h = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.table("jobs").update({"status": "running", "started_at": two_h, "attempts": 3}).eq("id", spent).execute()
    db.table("jobs").update({"status": "running", "started_at": two_h, "attempts": 2}).eq("id", fresh).execute()
    assert requeue_stale(db) == 1
    st = {r["id"]: r for r in db.table("jobs").select("id,status,error").in_("id", [spent, fresh]).execute().data}
    assert st[spent]["status"] == "failed" and st[spent]["error"] == "stale after 3 attempts" and st[fresh]["status"] == "queued"


def test_finish_sets_finished_at():
    jid = enqueue(db, "clean", T)
    claim(db)
    finish(db, jid, "done", {"output": "x"})
    r = db.table("jobs").select("*").eq("id", jid).single().execute().data
    assert r["status"] == "done" and r["finished_at"] and r["result"] == {"output": "x"}


@pytest.mark.parametrize("state", ["done", "cancelled", "queued"])
def test_finish_ignores_a_job_that_is_not_running(state):
    jid = enqueue(db, "clean", T)
    db.table("jobs").update({"status": state}).eq("id", jid).execute()
    finish(db, jid, "failed", error="late")
    r = db.table("jobs").select("status,error,finished_at").eq("id", jid).single().execute().data
    assert r["status"] == state and r["error"] is None and r["finished_at"] is None


def test_guard_sees_a_real_queued_job_and_ignores_test_rows():
    far = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    jid = db.table("jobs").insert({"kind": "clean", "payload": {"guard_probe": 1}, "run_after": far}).execute().data[0]["id"]
    try:
        assert jid in [r["id"] for r in real_jobs(db)]
        db.table("jobs").delete().eq("id", jid).execute()
        enqueue(db, "clean", T)
        assert real_jobs(db) == []
    finally:
        db.table("jobs").delete().eq("id", jid).execute()
