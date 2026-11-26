"""Two identical open jobs (same kind and argv, queued or running) must not exist: migration 0016's unique index refuses the second, `enqueue` returns the open twin."""
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from gtm.jobs import enqueue

DUP = {"code": "23505", "message": 'duplicate key value violates unique constraint "jobs_open_unique"', "details": None, "hint": None}
PAYLOAD = {"argv": ["--batch", "B1"], "n": 2}


class Fake:
    """A supabase query builder: every filter returns itself, `insert(...).execute()` raises `err`, `select(...).execute()` returns `rows`."""

    def __init__(self, err=None, rows=()):
        self.err, self.rows, self.verb = err, list(rows), None

    def table(self, name):
        assert name == "jobs"
        return self

    def insert(self, row):
        self.verb = "insert"
        return self

    def select(self, *cols):
        self.verb = "select"
        return self

    def __getattr__(self, name):  # eq, in_, contains, ...
        return lambda *a, **k: self

    def execute(self):
        if self.verb == "insert":
            if self.err:
                raise self.err
            return SimpleNamespace(data=[{"id": "new"}])
        return SimpleNamespace(data=self.rows)


def test_a_lost_race_returns_the_open_twins_id():
    twin = {"id": "open-1", "payload": {"argv": ["--batch", "B1"], "n": 1}}
    other = {"id": "other", "payload": {"argv": ["--batch", "B2"]}}
    assert enqueue(Fake(APIError(DUP), [other, twin]), "draft", PAYLOAD) == "open-1"


def test_a_unique_violation_with_no_open_twin_is_raised():
    with pytest.raises(APIError):
        enqueue(Fake(APIError(DUP), []), "draft", PAYLOAD)


def test_any_other_database_error_is_raised():
    with pytest.raises(APIError):
        enqueue(Fake(APIError({"code": "42501", "message": "denied"}), [{"id": "x", "payload": PAYLOAD}]), "draft", PAYLOAD)


# Real database. Kind TEST_dup_probe is no pass the worker runs, and payload.test makes claim_job skip it. Needs migration 0016 applied.
K = "TEST_dup_probe"
TEST_ARGV = ["--batch", "TEST_dup"]


@pytest.fixture
def db():
    from gtm.db import get_db

    d = get_db()
    d.table("jobs").delete().eq("kind", K).execute()
    yield d
    d.table("jobs").delete().eq("kind", K).execute()


def _row(argv=TEST_ARGV, status="queued", kind=K):
    return {"kind": kind, "status": status, "payload": {"argv": argv, "test": 1}}


def _open(db):
    return db.table("jobs").select("id").eq("kind", K).execute().data


@pytest.mark.db
@pytest.mark.parametrize("first", ["queued", "running"])
def test_a_second_identical_open_job_is_refused(db, first):
    db.table("jobs").insert(_row(status=first)).execute()
    with pytest.raises(APIError) as e:
        db.table("jobs").insert(_row()).execute()
    assert e.value.code == "23505" and len(_open(db)) == 1


@pytest.mark.db
def test_enqueue_returns_the_open_twin_not_a_second_row(db):
    a = enqueue(db, K, {"argv": TEST_ARGV, "test": 1})
    assert enqueue(db, K, {"argv": TEST_ARGV, "test": 1}) == a and len(_open(db)) == 1


@pytest.mark.db
@pytest.mark.parametrize("closed", ["done", "failed", "cancelled", "paused_budget"])
def test_a_job_that_is_not_queued_or_running_does_not_block_a_twin(db, closed):
    db.table("jobs").insert(_row(status=closed)).execute()
    db.table("jobs").insert(_row()).execute()
    assert len(_open(db)) == 2


@pytest.mark.db
def test_another_argv_is_not_a_twin(db):
    db.table("jobs").insert(_row()).execute()
    db.table("jobs").insert(_row(argv=["--batch", "TEST_other"])).execute()
    assert len(_open(db)) == 2
