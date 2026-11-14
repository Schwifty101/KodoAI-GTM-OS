import pytest

from gtm import draftcheck
from gtm.config import Settings
from gtm.db import get_db
from gtm.draft import build_followup
from gtm.draftcheck import run_check_drafts
from gtm.scrape import new_batch, place_to_lead
from test_draft import GOOD, OBJ


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    lead = db.table("leads").insert({**place_to_lead({"placeId": "REHEARSAL_A_chk", "title": "Glow Med Spa", "categories": ["Medical spa"], "state": "Texas"}, bid),
                                     "status": "drafted"}).execute().data[0]
    yield db, lead
    db.table("touches").delete().eq("lead_id", lead["id"]).execute()
    db.table("leads").delete().eq("id", lead["id"]).execute()
    db.table("batches").delete().eq("id", bid).execute()


def touch(db, lead, status, body, touch_no=1, subject="Glow Med Spa / booking", approved_at=None):
    return db.table("touches").insert({"lead_id": lead["id"], "touch_no": touch_no, "status": status, "subject": subject, "body": body, "objective": OBJ,
                                       "approved_at": approved_at, "problems": ["stale"] if status == "held" else []}).execute().data[0]["id"]


def row(db, tid):
    return db.table("touches").select("status,problems,approved_at").eq("id", tid).execute().data[0]


@pytest.mark.db
def test_edited_clean_touch_becomes_drafted(world):
    db, lead = world
    tid = touch(db, lead, "edited", GOOD)
    assert run_check_drafts(db, [tid]) == 1
    assert row(db, tid) == {"status": "drafted", "problems": [], "approved_at": None}


@pytest.mark.db
def test_edited_failing_touch_becomes_held_with_codes(world):
    db, lead = world
    tid = touch(db, lead, "edited", "too short", subject="Quick hello")
    run_check_drafts(db, [tid])
    r = row(db, tid)
    assert r["status"] == "held" and {"too_short", "bad_subject"} <= set(r["problems"])


@pytest.mark.db
def test_non_edited_touches_are_untouched(world):
    db, lead = world
    a, b = touch(db, lead, "held", "bad", touch_no=2), touch(db, lead, "approved", "bad", touch_no=3)
    assert run_check_drafts(db, [a, b]) == 0
    assert row(db, a)["status"] == "held" and row(db, a)["problems"] == ["stale"] and row(db, b)["status"] == "approved"


@pytest.mark.db
def test_edited_follow_up_is_checked_as_touch_2_and_needs_no_slash_subject(world):
    db, lead = world
    tid = touch(db, lead, "edited", build_followup(2, "Dana", "Glow Med Spa", OBJ), touch_no=2, subject="Re: Glow Med Spa")
    run_check_drafts(db, [tid])
    assert row(db, tid) == {"status": "drafted", "problems": [], "approved_at": None}


@pytest.mark.db
def test_ids_scope_leaves_other_edited_rows_alone(world):
    db, lead = world
    a, b = touch(db, lead, "edited", GOOD), touch(db, lead, "edited", GOOD, touch_no=2)
    assert run_check_drafts(db, [a]) == 1 and row(db, b)["status"] == "edited"


@pytest.mark.db
def test_recheck_clears_a_stale_approval(world):
    db, lead = world
    tid = touch(db, lead, "edited", GOOD, approved_at="2026-11-14T10:00:00+00:00")
    run_check_drafts(db, [tid])
    assert row(db, tid)["approved_at"] is None


@pytest.mark.db
def test_an_edit_during_the_check_leaves_the_row_edited(world, monkeypatch):
    db, lead = world
    tid = touch(db, lead, "edited", GOOD)
    real = draftcheck.check_draft

    def check_then_owner_edits(body, n):
        db.table("touches").update({"body": GOOD + " more"}).eq("id", tid).execute()
        return real(body, n)

    monkeypatch.setattr(draftcheck, "check_draft", check_then_owner_edits)
    run_check_drafts(db, [tid])
    assert row(db, tid)["status"] == "edited"


@pytest.mark.db
def test_the_footer_is_stripped_before_checking(world, monkeypatch):
    db, lead = world
    monkeypatch.setattr("gtm.draft.get_settings", lambda: Settings.from_env({"OPT_OUT_LINE": "Reply stop to opt out."}))
    t1 = touch(db, lead, "edited", GOOD + "\n\nReply stop to opt out.")
    t2 = touch(db, lead, "edited", build_followup(2, "Dana", "Glow Med Spa", OBJ) + "\n\nReply stop to opt out.", touch_no=2, subject="Re: x")
    assert run_check_drafts(db, [t1, t2]) == 2
    assert row(db, t1)["status"] == "drafted" and row(db, t2)["status"] == "drafted"
