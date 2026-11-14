import pytest

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


def touch(db, lead, status, body, touch_no=1, subject="Glow Med Spa / booking"):
    return db.table("touches").insert({"lead_id": lead["id"], "touch_no": touch_no, "status": status, "subject": subject, "body": body, "objective": OBJ,
                                       "problems": ["stale"] if status == "held" else []}).execute().data[0]["id"]


def row(db, tid):
    return db.table("touches").select("status,problems").eq("id", tid).execute().data[0]


@pytest.mark.db
def test_edited_clean_touch_becomes_drafted(world):
    db, lead = world
    tid = touch(db, lead, "edited", GOOD)
    assert run_check_drafts(db) >= 1
    assert row(db, tid) == {"status": "drafted", "problems": []}


@pytest.mark.db
def test_edited_failing_touch_becomes_held_with_codes(world):
    db, lead = world
    tid = touch(db, lead, "edited", "too short", subject="Quick hello")
    run_check_drafts(db)
    r = row(db, tid)
    assert r["status"] == "held" and {"too_short", "bad_subject"} <= set(r["problems"])


@pytest.mark.db
def test_non_edited_touches_are_untouched(world):
    db, lead = world
    a, b = touch(db, lead, "held", "bad", touch_no=2), touch(db, lead, "approved", "bad", touch_no=3)
    run_check_drafts(db)
    assert row(db, a) == {"status": "held", "problems": ["stale"]} and row(db, b)["status"] == "approved"


@pytest.mark.db
def test_edited_follow_up_is_checked_as_touch_2(world):
    db, lead = world
    tid = touch(db, lead, "edited", build_followup(2, "Dana", "Glow Med Spa", OBJ), touch_no=2, subject="Re: Glow Med Spa / booking")
    run_check_drafts(db)
    assert row(db, tid) == {"status": "drafted", "problems": []}
