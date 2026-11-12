import pytest

from gtm.costs import log_cost, spend_context
from gtm.db import get_db


@pytest.mark.db
def test_log_cost_inserts_row():
    db = get_db()
    note = "pytest-test-log-cost"
    try:
        log_cost("apify", 12, 0.05, note=note)
        rows = db.table("cost_log").select("*").eq("note", note).execute().data
        assert len(rows) == 1
        assert (rows[0]["provider"], float(rows[0]["units"]), float(rows[0]["usd"])) == ("apify", 12.0, 0.05)
    finally:
        db.table("cost_log").delete().eq("note", note).execute()


@pytest.fixture
def rows(monkeypatch):
    out = []

    class T:
        def insert(self, row):
            out.append(row)
            return self

        def execute(self):
            return None

    class DB:
        def table(self, name):
            assert name == "cost_log"
            return T()

    monkeypatch.setattr("gtm.costs.get_db", lambda: DB())
    return out


def test_log_cost_inherits_batch_and_lead_from_context(rows):
    with spend_context(batch_id="b1", lead_id="l1"):
        log_cost("serper", 1, None)
    assert rows[-1]["batch_id"] == "b1" and rows[-1]["lead_id"] == "l1"


def test_explicit_args_win(rows):
    with spend_context(batch_id="b1"):
        log_cost("x", 1, None, batch_id="b2")
    assert rows[-1]["batch_id"] == "b2"


def test_nested_contexts_merge_and_reset(rows):
    with spend_context(batch_id="b1"):
        with spend_context(lead_id="l1"):
            log_cost("x", 1, None)
        assert (rows[-1]["batch_id"], rows[-1]["lead_id"]) == ("b1", "l1")
        log_cost("x", 1, None)
        assert (rows[-1]["batch_id"], rows[-1]["lead_id"]) == ("b1", None)
    log_cost("x", 1, None)
    assert (rows[-1]["batch_id"], rows[-1]["lead_id"]) == (None, None)


def test_context_resets_after_exception(rows):
    with pytest.raises(ValueError):
        with spend_context(batch_id="b1", lead_id="l1"):
            raise ValueError
    log_cost("x", 1, None)
    assert (rows[-1]["batch_id"], rows[-1]["lead_id"]) == (None, None)
