import time

import pytest

from gtm.budget import BudgetExceeded
from gtm.db import get_db
from gtm.jobs import enqueue
from gtm.worker import _run_pass, run_one

db = get_db()


@pytest.fixture
def clean(no_real_jobs):
    def wipe():
        db.table("jobs").delete().eq("payload->>test", "1").execute()
    wipe()
    yield
    wipe()


def _job(jid):
    return db.table("jobs").select("*").eq("id", jid).single().execute().data


def _boom(exc):
    def f(kind, argv):
        raise exc
    return f


@pytest.mark.db
def test_run_one_success_marks_done_with_output(clean):
    jid = enqueue(db, "clean", {"test": 1, "argv": ["--batch", "x"]})
    seen = []
    assert run_one(db, lambda k, a: seen.append((k, a)) or "ok") == jid
    j = _job(jid)
    assert j["status"] == "done" and j["result"] == {"output": "ok"} and seen == [("clean", ["--batch", "x"])]


@pytest.mark.db
def test_run_one_budget_exceeded_marks_paused_budget(clean):
    jid = enqueue(db, "clean", {"test": 1})
    run_one(db, _boom(BudgetExceeded("cap")))
    j = _job(jid)
    assert j["status"] == "paused_budget" and "cap" in j["error"]


@pytest.mark.db
@pytest.mark.parametrize("exc", [RuntimeError("bad"), SystemExit("nope")])
def test_run_one_exception_marks_failed_with_error(clean, exc):
    jid = enqueue(db, "clean", {"test": 1})
    run_one(db, _boom(exc))
    j = _job(jid)
    assert j["status"] == "failed" and str(exc) in j["error"]


@pytest.mark.db
def test_run_one_unknown_kind_fails_without_running_anything(clean):
    jid = enqueue(db, "send", {"test": 1})
    run_one(db, _boom(AssertionError("must not run")))
    j = _job(jid)
    assert j["status"] == "failed" and "send" in j["error"]


@pytest.mark.db
def test_run_one_empty_queue_returns_none(clean):
    assert run_one(db, _boom(AssertionError("must not run"))) is None


def test_run_pass_parses_argv_with_the_real_parser():
    with pytest.raises(SystemExit):
        _run_pass("clean", [])


def test_enrich_pass_hitting_the_budget_cap_finishes_the_job_paused_budget(monkeypatch):
    from unittest.mock import MagicMock

    from gtm import cli, worker

    fdb = MagicMock()
    fdb.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [{"id": 1, "domain": "a.com"}]

    def finder(lead):
        raise BudgetExceeded("gemini cap")

    done = []
    monkeypatch.setattr(worker, "claim", lambda d: {"id": "j1", "kind": "enrich", "payload": {"argv": ["--batch", "b", "--finders", "site"]}})
    monkeypatch.setattr(worker, "finish", lambda d, i, s, result=None, error=None: done.append((i, s, error)))
    monkeypatch.setattr(cli, "get_db", lambda: fdb)
    monkeypatch.setattr(cli, "HunterPool", lambda *a, **k: None)
    monkeypatch.setattr(cli, "get_settings", lambda: MagicMock())
    monkeypatch.setattr(cli, "site_owner_finder", lambda pool: finder)
    worker.run_one(None)
    assert done == [("j1", "paused_budget", "gemini cap")]


def test_run_one_keyboard_interrupt_cancels_the_job_and_reraises(monkeypatch):
    from gtm import worker

    done = []
    monkeypatch.setattr(worker, "claim", lambda d: {"id": "j1", "kind": "clean", "payload": {}})
    monkeypatch.setattr(worker, "finish", lambda d, i, s, result=None, error=None: done.append((i, s, error)))
    with pytest.raises(KeyboardInterrupt):
        run_one(None, _boom(KeyboardInterrupt()))
    assert done == [("j1", "cancelled", "interrupted")]


def test_beating_calls_heartbeat_while_the_block_runs(monkeypatch):
    from gtm import worker

    beats = []
    monkeypatch.setattr(worker, "heartbeat", lambda d, i: beats.append(i))
    with worker.beating(None, "j1", every=0.01):
        time.sleep(0.1)
    n = len(beats)
    assert n >= 2
    time.sleep(0.05)
    assert len(beats) == n


def test_run_one_beats_during_the_pass(monkeypatch):
    from gtm import worker

    beats = []
    monkeypatch.setattr(worker, "BEAT_SECONDS", 0.01)
    monkeypatch.setattr(worker, "claim", lambda d: {"id": "j1", "kind": "clean", "payload": {}})
    monkeypatch.setattr(worker, "finish", lambda *a, **k: None)
    monkeypatch.setattr(worker, "heartbeat", lambda d, i: beats.append(i))
    run_one(None, lambda kind, argv: time.sleep(0.1) or "ok")
    assert len(beats) >= 2
