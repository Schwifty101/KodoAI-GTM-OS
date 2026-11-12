import pytest

from gtm.budget import BudgetExceeded
from gtm.db import get_db
from gtm.jobs import enqueue
from gtm.worker import _run_pass, run_one

db = get_db()


@pytest.fixture
def clean():
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
