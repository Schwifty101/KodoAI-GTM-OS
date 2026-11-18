from datetime import datetime, timedelta, timezone

import pytest

from gtm import schedule
from gtm.db import get_db
from gtm.jobs import enqueue as real_enqueue
from gtm.settings_store import DEFAULTS

pytestmark = pytest.mark.db
db = get_db()
T = {"test": 1}


K = "walk_test"  # own kind: real walk jobs never interfere, and we never touch them


def _walks_today():
    return db.table("jobs").select("id,payload").eq("kind", K).gte("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%d")).execute().data


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    cfg = dict(DEFAULTS, walk_schedule_enabled=True, walk_hour_utc=13)
    monkeypatch.setattr(schedule, "setting", lambda key, db=None: cfg[key])
    monkeypatch.setattr(schedule, "enqueue", lambda db, kind, payload=None, **kw: real_enqueue(db, kind, {**(payload or {}), **T}, run_after=datetime.now(timezone.utc) + timedelta(days=3650)))  # no worker can claim it
    wipe = lambda: db.table("jobs").delete().eq("kind", K).execute()
    wipe()
    yield cfg
    wipe()


def at(hour):
    return datetime.now(timezone.utc).replace(hour=hour, minute=0)


def test_disabled_enqueues_nothing(clean):
    clean["walk_schedule_enabled"] = False
    assert schedule.tick(db, kind=K, now=at(20)) is None and not _walks_today()


def test_enabled_before_the_hour_enqueues_nothing():
    assert schedule.tick(db, kind=K, now=at(12)) is None and not _walks_today()


def test_enabled_after_the_hour_enqueues_once_per_utc_day():
    jid = schedule.tick(db, kind=K, now=at(13))
    assert jid and schedule.tick(db, kind=K, now=at(14)) is None
    row = db.table("jobs").select("kind,payload").eq("id", jid).execute().data[0]
    assert row["kind"] == K and row["payload"]["argv"] == ["--tiles", "3"]
    assert len(_walks_today()) == 1


def test_a_job_created_yesterday_does_not_block():
    old = real_enqueue(db, K, T)
    db.table("jobs").update({"created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}).eq("id", old).execute()
    assert schedule.tick(db, kind=K, now=at(13))


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_or_cancelled_walk_today_still_blocks_a_second(status):
    jid = real_enqueue(db, K, T)
    db.table("jobs").update({"status": status}).eq("id", jid).execute()
    assert schedule.tick(db, kind=K, now=at(13)) is None


def test_a_real_walk_job_today_does_not_block_and_is_left_alone():
    real = real_enqueue(db, "walk", {"argv": []}, run_after=datetime.now(timezone.utc) + timedelta(days=3650))
    try:
        assert schedule.tick(db, kind=K, now=at(13))
        assert db.table("jobs").select("status").eq("id", real).execute().data[0]["status"] == "queued"
    finally:
        db.table("jobs").delete().eq("id", real).execute()


class _Jobs:
    """Fake jobs table: queue_tick only asks 'any sheet-queue job since midnight?'."""
    def __init__(self, existing=()):
        self.data = list(existing)

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return self


def _qt(monkeypatch, on=True, hour=7, existing=()):
    cfg = {"sheet_queue_on": on, "sheet_queue_hour_utc": hour}
    monkeypatch.setattr(schedule, "setting", lambda key, db=None: cfg[key])
    calls = []
    monkeypatch.setattr(schedule, "enqueue", lambda db, kind, payload=None, **kw: calls.append((kind, payload)) or "job1")
    return calls, _Jobs(existing)


def test_queue_tick_enqueues_once_per_day_and_respects_switch_and_hour(monkeypatch):
    now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
    calls, fake = _qt(monkeypatch, on=False)
    assert schedule.queue_tick(fake, now) is None and not calls  # switch off
    calls, fake = _qt(monkeypatch, hour=9)
    assert schedule.queue_tick(fake, now) is None and not calls  # hour not reached
    calls, fake = _qt(monkeypatch, existing=[{"id": 1}])
    assert schedule.queue_tick(fake, now) is None and not calls  # already queued today, any status
    calls, fake = _qt(monkeypatch)
    assert schedule.queue_tick(fake, now) == "job1" and calls == [("sheet-queue", {"argv": ["--confirm"]})]
