from datetime import datetime, timedelta, timezone

import pytest

from gtm import schedule
from gtm.db import get_db
from gtm.jobs import enqueue as real_enqueue
from gtm.settings_store import DEFAULTS

pytestmark = pytest.mark.db
db = get_db()
T = {"test": 1}


def _walks_today():
    return db.table("jobs").select("id,payload").eq("kind", "walk").gte("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")).execute().data


@pytest.fixture(autouse=True)
def clean(no_real_jobs, monkeypatch):
    if any(r["payload"].get("test") != 1 for r in _walks_today()):
        pytest.skip("a real walk job exists today: tick tests would see it")
    cfg = dict(DEFAULTS, walk_schedule_enabled=True, walk_hour_utc=13)
    monkeypatch.setattr(schedule, "setting", lambda key, db=None: cfg[key])
    monkeypatch.setattr(schedule, "enqueue", lambda db, kind, payload=None, **kw: real_enqueue(db, kind, {**(payload or {}), **T}, **kw))
    wipe = lambda: db.table("jobs").delete().eq("payload->>test", "1").execute()
    wipe()
    yield cfg
    wipe()


def at(hour):
    return datetime.now(timezone.utc).replace(hour=hour, minute=0)


def test_disabled_enqueues_nothing(clean):
    clean["walk_schedule_enabled"] = False
    assert schedule.tick(db, at(20)) is None and not _walks_today()


def test_enabled_before_the_hour_enqueues_nothing():
    assert schedule.tick(db, at(12)) is None and not _walks_today()


def test_enabled_after_the_hour_enqueues_once_per_utc_day():
    jid = schedule.tick(db, at(13))
    assert jid and schedule.tick(db, at(14)) is None
    row = db.table("jobs").select("kind,payload").eq("id", jid).execute().data[0]
    assert row["kind"] == "walk" and row["payload"]["argv"] == ["--tiles", "3"]
    assert len(_walks_today()) == 1


def test_a_job_created_yesterday_does_not_block():
    old = real_enqueue(db, "walk", T)
    db.table("jobs").update({"created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}).eq("id", old).execute()
    assert schedule.tick(db, at(13))


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_or_cancelled_walk_today_still_blocks_a_second(status):
    jid = real_enqueue(db, "walk", T)
    db.table("jobs").update({"status": status}).eq("id", jid).execute()
    assert schedule.tick(db, at(13)) is None
