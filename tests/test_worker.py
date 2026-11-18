import time

import pytest

from gtm.budget import BudgetExceeded
from gtm.db import get_db
from gtm import worker
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
    assert run_one(db, include_test=True, run_pass=lambda k, a: seen.append((k, a)) or "ok") == jid
    j = _job(jid)
    assert j["status"] == "done" and j["result"] == {"output": "ok"} and seen == [("clean", ["--batch", "x"])]


@pytest.mark.db
def test_run_one_budget_exceeded_marks_paused_budget(clean):
    jid = enqueue(db, "clean", {"test": 1})
    run_one(db, include_test=True, run_pass=_boom(BudgetExceeded("cap")))
    j = _job(jid)
    assert j["status"] == "paused_budget" and "cap" in j["error"]


@pytest.mark.db
@pytest.mark.parametrize("exc", [RuntimeError("bad"), SystemExit("nope")])
def test_run_one_exception_marks_failed_with_error(clean, exc):
    jid = enqueue(db, "clean", {"test": 1})
    run_one(db, include_test=True, run_pass=_boom(exc))
    j = _job(jid)
    assert j["status"] == "failed" and str(exc) in j["error"]


@pytest.mark.db
def test_run_one_unknown_kind_fails_without_running_anything(clean):
    jid = enqueue(db, "send", {"test": 1})
    run_one(db, include_test=True, run_pass=_boom(AssertionError("must not run")))
    j = _job(jid)
    assert j["status"] == "failed" and "send" in j["error"]


@pytest.mark.db
def test_run_one_empty_queue_returns_none(clean):
    assert run_one(db, include_test=True, run_pass=_boom(AssertionError("must not run"))) is None


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
    monkeypatch.setattr(worker, "claim", lambda d, **k: {"id": "j1", "kind": "enrich", "payload": {"argv": ["--batch", "b", "--finders", "site"]}})
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
    monkeypatch.setattr(worker, "claim", lambda d, **k: {"id": "j1", "kind": "clean", "payload": {}})
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
    monkeypatch.setattr(worker, "claim", lambda d, **k: {"id": "j1", "kind": "clean", "payload": {}})
    monkeypatch.setattr(worker, "finish", lambda *a, **k: None)
    monkeypatch.setattr(worker, "heartbeat", lambda d, i: beats.append(i))
    run_one(None, lambda kind, argv: time.sleep(0.1) or "ok")
    assert len(beats) >= 2


def test_worker_main_starts_the_send_loop_thread(monkeypatch):
    started = []

    class Rec:
        def __init__(self, target=None, daemon=None, **kw):
            self.target, self.daemon = target, daemon

        def start(self):
            started.append(self)

    def stop(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.threading, "Thread", Rec)
    monkeypatch.setattr(worker, "get_db", lambda: object())
    monkeypatch.setattr(worker, "requeue_stale", stop)
    monkeypatch.setattr(worker.signal, "signal", lambda *a: None)
    worker.main()
    assert [t.target for t in started] == [worker.send_loop] and started[0].daemon is True


def test_send_loop_survives_an_exception(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("gmail down")

    def stop(_):
        if len(calls) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker, "get_db", lambda: object())
    monkeypatch.setattr(worker, "send_tick", boom)
    monkeypatch.setattr(worker.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        worker.send_loop(every=0)
    assert len(calls) == 2


def test_send_loop_prints_the_tick_result_only_when_something_happened(monkeypatch, capsys):
    results = iter([{"off": 1}, {"replies": {}, "scheduled": 0, "send": {}, "bad_tz": 0}, {"replies": {}, "scheduled": 1, "send": {"sent": 2, "stranded": 1}, "paused": 1, "bad_tz": 0}])
    calls = []

    def tick(*a, **k):
        calls.append(1)
        return next(results)

    def stop(_):
        if len(calls) >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(worker, "get_db", lambda: object())
    monkeypatch.setattr(worker, "send_tick", tick)
    monkeypatch.setattr(worker.time, "sleep", stop)
    with pytest.raises(KeyboardInterrupt):
        worker.send_loop(every=0)
    out = capsys.readouterr().out
    assert out.count("send tick:") == 1 and "'sent': 2" in out


def test_worker_allows_the_sheet_kinds():
    assert {"import-sheet", "verify-sheet", "sheet-queue", "sheet-paint"} <= worker.ALLOWED
