from datetime import date

import pytest

from gtm.db import get_db
from gtm.redraft import run_redraft
from gtm.scrape import new_batch, place_to_lead
from test_draft import GOOD, LEAD, OBJ

NEW = {"subject": "Glow Med Spa / booking, warmer", "body": GOOD, "objective": OBJ}


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    ids = []
    for i in range(5):
        row = {**place_to_lead({"placeId": f"REHEARSAL_A_rd{i}", "title": "Glow Med Spa", "categories": ["Medical spa"], "state": "Texas"}, bid),
               "status": "drafted", "owner_name": "Dana W", "vector": "capacity", "signal_led": False, "signal": LEAD["signal"]}
        ids.append(db.table("leads").insert(row).execute().data[0]["id"])
    yield db, bid, ids
    db.table("touches").delete().in_("lead_id", ids).execute()
    db.table("leads").delete().in_("id", ids).execute()
    db.table("batches").delete().eq("id", bid).execute()


def put(db, lead_id, status):
    return db.table("touches").insert({"lead_id": lead_id, "touch_no": 1, "status": status, "subject": "old", "body": "old", "objective": "old",
                                       "approved_at": "2026-11-14T10:00:00+00:00" if status == "approved" else None}).execute().data[0]["id"]


def row(db, tid):
    return db.table("touches").select("*").eq("id", tid).execute().data[0]


def llm_ok(system, prompt):
    llm_ok.prompts.append(prompt)
    return NEW


llm_ok.prompts = []


@pytest.mark.db
def test_redraft_replaces_unsent_drafts_and_records_instruction(world):
    db, bid, ids = world
    tids = [put(db, ids[0], "drafted"), put(db, ids[1], "held"), put(db, ids[2], "edited")]
    assert run_redraft(db, llm_ok, bid, "  warmer opener ", date(2026, 11, 14)) == 3
    for t in tids:
        r = row(db, t)
        assert (r["status"], r["subject"], r["problems"], r["approved_at"]) == ("drafted", NEW["subject"], [], None)
    assert "Owner instruction for this batch: warmer opener" in llm_ok.prompts[-1]
    assert db.table("batches").select("draft_instruction").eq("id", bid).execute().data[0]["draft_instruction"] == "warmer opener"


@pytest.mark.db
def test_redraft_leaves_approved_and_sent_alone(world):
    db, bid, ids = world
    tids = [put(db, ids[i], s) for i, s in enumerate(["approved", "scheduled", "sending", "sent"])]
    assert run_redraft(db, llm_ok, bid, "x", date(2026, 11, 14)) == 0
    assert [row(db, t)["subject"] for t in tids] == ["old"] * 4 and row(db, tids[0])["approved_at"]


@pytest.mark.db
def test_empty_instruction_is_refused(world):
    db, bid, ids = world
    t = put(db, ids[0], "drafted")
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            run_redraft(db, llm_ok, bid, bad, date(2026, 11, 14))
    assert row(db, t)["subject"] == "old"


@pytest.mark.db
def test_redraft_failure_marks_held_not_lost(world):
    db, bid, ids = world
    a, b = put(db, ids[0], "drafted"), put(db, ids[1], "drafted")
    calls = []

    def flaky(system, prompt):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("vertex down")
        return NEW

    assert run_redraft(db, flaky, bid, "x", date(2026, 11, 14)) == 1
    failed, fresh = sorted((row(db, a), row(db, b)), key=lambda r: r["subject"] != "old")  # lead order is by uuid: the first one fails
    assert (failed["status"], failed["problems"], failed["body"]) == ("held", ["redraft_failed"], "old") and fresh["subject"] == NEW["subject"]
