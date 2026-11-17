from datetime import date

import pytest

from gtm.budget import BudgetExceeded
from gtm.costs import log_cost
from gtm.db import get_db
from gtm.redraft import run_redraft
from gtm.scrape import new_batch, place_to_lead
from test_draft import GOOD, LEAD, OBJ

NEW = {"subject": "Glow Med Spa / booking, warmer", "body": GOOD, "objective": OBJ}
TODAY = date(2026, 11, 14)


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
    db.table("cost_log").delete().eq("batch_id", bid).execute()
    db.table("touches").delete().in_("lead_id", ids).execute()
    db.table("leads").delete().in_("id", ids).execute()
    db.table("batches").delete().eq("id", bid).execute()


def put(db, lead_id, status):
    return db.table("touches").insert({"lead_id": lead_id, "touch_no": 1, "status": status, "subject": "old", "body": "old", "objective": "old",
                                       "approved_at": "2026-11-14T10:00:00+00:00" if status == "approved" else None}).execute().data[0]["id"]


def row(db, tid):
    return db.table("touches").select("*").eq("id", tid).execute().data[0]


def recording(answer=NEW):
    def llm(system, prompt):
        llm.prompts.append(prompt)
        return answer

    llm.prompts = []
    return llm


@pytest.mark.db
def test_redraft_replaces_unsent_drafts_and_records_instruction(world):
    db, bid, ids = world
    tids = [put(db, ids[0], "drafted"), put(db, ids[1], "held"), put(db, ids[2], "edited")]
    llm = recording()
    assert run_redraft(db, llm, bid, "  warmer opener ", TODAY) == 3
    for t in tids:
        r = row(db, t)
        assert (r["status"], r["subject"], r["problems"], r["approved_at"]) == ("drafted", NEW["subject"], [], None)
    assert len(llm.prompts) == 3 and all("Owner instruction for this batch: warmer opener" in p for p in llm.prompts)
    assert db.table("batches").select("draft_instruction").eq("id", bid).execute().data[0]["draft_instruction"] == "warmer opener"


@pytest.mark.db
def test_redraft_leaves_approved_and_sent_alone_and_never_calls_the_model_for_them(world):
    db, bid, ids = world
    tids = [put(db, ids[i], s) for i, s in enumerate(["approved", "scheduled", "sending", "sent"])]
    llm = recording()
    assert run_redraft(db, llm, bid, "x", TODAY) == 0
    assert llm.prompts == [] and [row(db, t)["subject"] for t in tids] == ["old"] * 4 and row(db, tids[0])["approved_at"]


@pytest.mark.db
def test_empty_instruction_is_refused(world):
    db, bid, ids = world
    t = put(db, ids[0], "drafted")
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            run_redraft(db, recording(), bid, bad, TODAY)
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

    assert run_redraft(db, flaky, bid, "x", TODAY) == 1
    failed, fresh = sorted((row(db, a), row(db, b)), key=lambda r: r["subject"] != "old")  # lead order is by uuid: the first one fails
    assert (failed["status"], failed["problems"], failed["body"]) == ("held", ["redraft_failed"], "old") and fresh["subject"] == NEW["subject"]


@pytest.mark.db
@pytest.mark.parametrize("fails", [True, False])
def test_an_approval_that_lands_during_the_model_call_is_not_overwritten(world, fails):
    db, bid, ids = world
    t = put(db, ids[0], "drafted")

    def llm(system, prompt):
        db.table("touches").update({"status": "approved", "approved_at": "2026-11-14T11:00:00+00:00"}).eq("id", t).execute()
        if fails:
            raise ValueError("vertex down")
        return NEW

    run_redraft(db, llm, bid, "x", TODAY)
    r = row(db, t)
    assert (r["status"], r["subject"], r["problems"]) == ("approved", "old", []) and r["approved_at"].startswith("2026-11-14T11:00:00")


@pytest.mark.db
def test_unedited_row_is_redrafted_and_edit_during_call_is_kept(world, capsys):
    db, bid, ids = world
    a, b = put(db, ids[0], "drafted"), put(db, ids[1], "drafted")

    def llm(system, prompt):  # the owner edits one row, during the first call only
        if not llm.done:
            llm.done = True
            # which lead goes first is by uuid, so edit both: the row in flight is skipped, the other was read after the edit and is redrafted
            db.table("touches").update({"status": "edited", "subject": "mine", "body": "mine"}).in_("id", [a, b]).execute()
        return NEW

    llm.done = False

    assert run_redraft(db, llm, bid, "x", TODAY) == 1
    rows = [row(db, t) for t in (a, b)]
    assert sorted(r["subject"] for r in rows) == sorted(["mine", NEW["subject"]])
    assert next(r for r in rows if r["subject"] == "mine")["status"] == "edited"
    assert "skipped_edited 1" in capsys.readouterr().out


@pytest.mark.db
def test_edit_during_failed_call_is_not_demoted(world):
    db, bid, ids = world
    t = put(db, ids[0], "drafted")

    def llm(system, prompt):
        db.table("touches").update({"status": "edited", "subject": "mine", "body": "mine"}).eq("id", t).execute()
        raise ValueError("vertex down")

    assert run_redraft(db, llm, bid, "x", TODAY) == 0
    r = row(db, t)
    assert (r["status"], r["subject"], r["problems"]) == ("edited", "mine", [])


@pytest.mark.db
def test_budget_exceeded_propagates_and_later_drafts_stay_untouched(world):
    db, bid, ids = world
    tids = [put(db, ids[i], "drafted") for i in range(3)]
    calls = []

    def llm(system, prompt):
        calls.append(1)
        if len(calls) == 2:
            raise BudgetExceeded("cap")
        return NEW

    with pytest.raises(BudgetExceeded):
        run_redraft(db, llm, bid, "x", TODAY)
    rows = [row(db, t) for t in tids]
    assert len(calls) == 2 and sorted(r["subject"] for r in rows) == [NEW["subject"], "old", "old"] and {r["status"] for r in rows} == {"drafted"}
    assert all(r["problems"] == [] for r in rows)


@pytest.mark.db
def test_stopped_and_blocked_leads_get_no_model_call(world):
    db, bid, ids = world
    replied, suppressed, ok = (put(db, ids[i], "drafted") for i in range(3))
    db.table("leads").update({"status": "replied"}).eq("id", ids[0]).execute()
    db.table("leads").update({"owner_email": "dana@rehearsal-a-rd.example"}).eq("id", ids[1]).execute()
    db.table("suppression").insert({"domain": "rehearsal-a-rd.example", "reason": "pytest-rd"}).execute()
    llm = recording()
    try:
        assert run_redraft(db, llm, bid, "x", TODAY) == 1 and len(llm.prompts) == 1
    finally:
        db.table("suppression").delete().eq("reason", "pytest-rd").execute()
    assert row(db, replied)["subject"] == row(db, suppressed)["subject"] == "old" and row(db, ok)["subject"] == NEW["subject"]


@pytest.mark.db
def test_redraft_spend_is_logged_with_batch_and_lead(world):
    db, bid, ids = world
    put(db, ids[0], "drafted")

    def llm(system, prompt):
        log_cost("gemini", 1, 0.0, note="REHEARSAL_A_redraft")
        return NEW

    run_redraft(db, llm, bid, "x", TODAY)
    rows = db.table("cost_log").select("batch_id,lead_id").eq("note", "REHEARSAL_A_redraft").eq("batch_id", bid).execute().data
    assert rows == [{"batch_id": bid, "lead_id": ids[0]}]
