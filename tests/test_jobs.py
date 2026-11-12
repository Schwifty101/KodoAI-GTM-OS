from datetime import datetime, timedelta, timezone

import pytest

from gtm.db import get_db
from gtm.jobs import claim, enqueue, finish, requeue_stale

pytestmark = pytest.mark.db
db = get_db()
T = {"test": 1}


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        db.table("jobs").delete().eq("payload->>test", "1").execute()
    wipe()
    yield
    wipe()


def _drain_others():
    # claim() takes the oldest queued job, so park any real queued job out of the way
    return db.table("jobs").select("id").eq("status", "queued").neq("payload->>test", "1").execute().data


def test_enqueue_then_claim_returns_the_job_running():
    assert not _drain_others()
    jid = enqueue(db, "clean", T)
    j = claim(db)
    assert j["id"] == jid and j["status"] == "running" and j["started_at"]


def test_claim_is_atomic_second_claim_gets_nothing():
    assert not _drain_others()
    enqueue(db, "clean", T)
    assert [x for x in (claim(db), claim(db)) if x] and claim(db) is None


def test_future_run_after_is_not_claimed():
    assert not _drain_others()
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


def test_finish_sets_finished_at():
    jid = enqueue(db, "clean", T)
    finish(db, jid, "done", {"output": "x"})
    r = db.table("jobs").select("*").eq("id", jid).single().execute().data
    assert r["status"] == "done" and r["finished_at"] and r["result"] == {"output": "x"}
