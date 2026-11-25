from datetime import date, timedelta
from pathlib import Path

import pytest

from gtm.config import Settings
from gtm.db import get_db
from gtm.draft import APPROVED_CLIENTS, build_followup, check_draft, check_subject, strip_footer,draft_touch1, footer, run_draft, run_followups, touch_date
from gtm.mailboxes import assign_mailbox
from gtm.scrape import new_batch, place_to_lead

GOOD = """Dana,

I'm Soban, founder of KodoAI. We've worked with Rolls-Royce, Saudi Aramco and Patagonia.

Glow Med Spa is hiring a front desk coordinator. Booking still runs through phone calls and Instagram DMs.

We build custom AI systems around keeping rising booking and follow-up volume from becoming more front-desk work.

Is reducing the workload attached to that hire something you're actively working on this quarter?

Soban | Founder, KodoAI"""
OPTIONAL = " I think we could take repetitive booking follow-up off that person's plate."


def test_good_touch_1_passes():
    assert check_draft(GOOD, 1) == []


def words(t):
    return len(t.split())


def test_the_good_fixture_is_inside_the_word_and_sentence_limits():
    assert 45 <= words(GOOD) <= 70


def test_touch_1_over_70_words_fails():
    assert "too_long" in check_draft(GOOD.replace("work.\n", "work." + OPTIONAL + "\n"), 1)


def test_touch_1_under_45_words_fails():
    short = "Dana,\n\nI'm Soban, founder of KodoAI. We've worked with Rolls-Royce and Patagonia.\n\nIs that something you're working on?\n\nSoban | Founder, KodoAI"
    assert "too_short" in check_draft(short, 1)


@pytest.mark.parametrize("bad,problem", [
    (GOOD.replace("front desk coordinator.", "front desk coordinator — again."), "em_dash"),
    (GOOD.replace("work.\n", "work. Why wait?\n"), "not_one_question"),
    (GOOD.replace("Booking still", "I wanted to reach out. Booking still"), "banned_phrase"),
    (GOOD.replace("custom AI systems", "seamless AI systems"), "banned_phrase"),
    (GOOD.replace("Patagonia", "Pfizer"), "unapproved_client"),
    (GOOD.replace("Rolls-Royce, Saudi Aramco and Patagonia", "Rolls-Royce"), "client_count"),
    (GOOD.replace("We've worked with", "Our customers include"), "client_phrasing"),
    (GOOD.replace("We've worked with", "Through Bluegile we've worked with"), "bluegile"),
    (GOOD.replace("this quarter?", "this quarter, or not right now?"), "soft_opt_out"),
    (GOOD.replace("front desk coordinator", "3 front desk coordinators"), "number"),
    (GOOD.replace("Is reducing", "Can we set up a demo? Is reducing"), "offer"),
    (GOOD.replace("Dana,\n\n", ""), "missing_greeting"),
    (GOOD.replace("\n\nGlow", " Glow").replace("\n\nWe build", " We build").replace("\n\nIs reducing", " Is reducing"), "paragraphs"),
])
def test_touch_1_rule_violations_are_flagged(bad, problem):
    assert problem in check_draft(bad, 1)


def test_touch_1_must_end_on_the_question():
    assert "not_one_question" in check_draft(GOOD.replace("Is reducing the workload attached to that hire something you're actively working on this quarter?", "Is that active this quarter? We build things."), 1)


def test_approved_clients_are_pinned_to_the_master_prompt():
    text = Path("MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md").read_text()
    assert all(c in text for c in APPROVED_CLIENTS) and "Rolls-Royce" in APPROVED_CLIENTS and "Patreon" not in APPROVED_CLIENTS


OBJ = "easier phone and DM booking"


def test_touch_2_and_3_templates_pass_their_own_checks():
    t2, t3 = build_followup(2, "Dana", "Glow Med Spa", OBJ), build_followup(3, "Dana", "Glow Med Spa", OBJ)
    assert t2 == "Dana,\n\nIs easier phone and DM booking something you're working on right now, or is it not a priority?\n\nSoban"
    assert t3.startswith("Dana,\n\nWe're choosing med-spa partners who are ready to make easier phone and DM booking a priority this quarter.")
    assert t3.endswith("Is that where Glow Med Spa is right now?\n\nSoban")
    assert check_draft(t2, 2) == [] and check_draft(t3, 3) == []


def test_there_is_no_touch_4():
    with pytest.raises(ValueError):
        build_followup(4, "Dana", "Glow", OBJ)
    with pytest.raises(ValueError):
        touch_date(date(2026, 11, 10), 4)


def test_touch_dates_are_day_0_3_7():
    d = date(2026, 11, 10)
    assert [touch_date(d, n) for n in (1, 2, 3)] == [d, d + timedelta(3), d + timedelta(7)]


def test_footer_is_empty_when_nothing_is_configured():
    assert footer(Settings.from_env({})) == ""


def test_footer_appends_only_configured_values():
    s = Settings.from_env({"OPT_OUT_LINE": "Reply stop to opt out.", "POSTAL_ADDRESS": ""})
    assert footer(s) == "Reply stop to opt out."
    s = Settings.from_env({"AD_DISCLOSURE": "This is an advertisement.", "OPT_OUT_LINE": "Reply stop.", "POSTAL_ADDRESS": "1 Main St"})
    assert footer(s) == "This is an advertisement.\nReply stop.\n1 Main St"


def llm_returning(*answers):
    seq = list(answers)
    calls = []

    def llm(system, prompt):
        calls.append(prompt)
        return seq.pop(0) if len(seq) > 1 else seq[0]

    llm.calls = calls
    return llm


LEAD = {"name": "Glow Med Spa", "owner_name": "Dana W", "vector": "capacity", "signal_led": False,
        "signal": {"current_signal": None, "relevant_handoff": {"text": "Booking runs through phone and DMs", "url": "u", "quote": "q"}}}


def test_draft_touch_1_retries_with_the_problems_and_returns_the_clean_draft():
    bad = {"subject": "Glow Med Spa / booking", "body": GOOD.replace("front desk", "front desk —"), "objective": OBJ}
    good = {"subject": "Glow Med Spa / booking handoff", "body": GOOD, "objective": OBJ}
    llm = llm_returning(bad, good)
    assert draft_touch1(llm, LEAD) == {**good, "problems": []}
    assert len(llm.calls) == 2 and "em_dash" in llm.calls[1]


def test_draft_touch_1_gives_up_after_three_bad_attempts_and_returns_the_last_problems():
    bad = {"subject": "Glow Med Spa / booking", "body": "too short", "objective": OBJ}
    llm = llm_returning(bad)
    d = draft_touch1(llm, LEAD)
    assert len(llm.calls) == 3 and d["body"] == "too short" and "too_short" in d["problems"]


def test_a_draft_with_a_subject_missing_the_company_slash_pattern_is_flagged():
    bad = {"subject": "Quick hello", "body": GOOD, "objective": OBJ}
    assert "bad_subject" in draft_touch1(llm_returning(bad), LEAD)["problems"]


def test_instruction_reaches_the_prompt():
    good = {"subject": "Glow Med Spa / booking", "body": GOOD, "objective": OBJ}
    llm = llm_returning(good)
    draft_touch1(llm, LEAD, instruction="warmer opener")
    assert "Owner instruction for this batch: warmer opener" in llm.calls[0]


def test_empty_model_answer_is_held_not_a_crash():
    d = draft_touch1(llm_returning({}), LEAD)
    assert d["subject"] == d["body"] == d["objective"] == "" and {"bad_subject", "no_objective"} <= set(d["problems"])
    assert draft_touch1(llm_returning(None), LEAD)["problems"]


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    mbs = db.table("mailboxes").insert([{"address": f"pytest-mb{i}@example.com", "daily_cap": 40, "enabled_on": "2026-01-01"} for i in (1, 2)]).execute().data
    items = [{"placeId": f"TEST_{i}", "title": "Glow Med Spa", "website": f"https://glow{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(3)]
    sig = LEAD["signal"]
    rows = [{**place_to_lead(it, bid), "status": "selected", "approved": n < 2, "owner_name": "Dana W", "owner_title": "Owner", "owner_email": f"dana@glow{n}.com",
             "email_verified": True, "vector": "capacity", "signal_led": False, "signal": sig} for n, it in enumerate(items)]
    db.table("leads").insert(rows).execute()
    yield db, bid, mbs
    db.table("suppression").delete().like("reason", "pytest%").execute()
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("mailboxes").delete().like("address", "pytest-mb%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def lead_row(db, i):
    return db.table("leads").select("*").eq("place_id", f"TEST_{i}").execute().data[0]


@pytest.mark.db
def test_assign_mailbox_spreads_load_and_is_sticky(world):
    db, bid, mbs = world
    ids = [r["id"] for r in db.table("leads").select("id").eq("batch_id", bid).order("place_id").execute().data]
    only = {m["id"] for m in mbs}
    first = [assign_mailbox(db, i, only=only) for i in ids[:2]]
    assert sorted(first) == sorted(m["id"] for m in mbs)  # least loaded each time, so the two go to different mailboxes
    assert assign_mailbox(db, ids[0], only=only) == first[0]  # sticky


@pytest.mark.db
def test_assign_mailbox_ignores_paused_and_not_yet_enabled_mailboxes(world):
    db, bid, mbs = world
    db.table("mailboxes").update({"paused": True}).eq("id", mbs[0]["id"]).execute()
    db.table("mailboxes").update({"enabled_on": "2999-01-01"}).eq("id", mbs[1]["id"]).execute()
    lid = db.table("leads").select("id").eq("batch_id", bid).limit(1).execute().data[0]["id"]
    with pytest.raises(RuntimeError):
        assign_mailbox(db, lid, only={m["id"] for m in mbs})


@pytest.mark.db
def test_clean_draft_is_stored_without_gmail(world):
    db, bid, mbs = world
    good = {"subject": "Glow Med Spa / phone and DM booking", "body": GOOD, "objective": OBJ}
    n = run_draft(db, llm_returning(good), bid, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs})
    assert n == 2  # the unapproved lead is not drafted
    a, c = lead_row(db, 0), lead_row(db, 2)
    assert a["status"] == "drafted" and a["mailbox_id"] in {m["id"] for m in mbs} and c["status"] == "selected"
    t = db.table("touches").select("*").eq("lead_id", a["id"]).execute().data[0]
    assert (t["touch_no"], t["status"], t["subject"], t["objective"], t["scheduled_for"], t["problems"]) == (1, "drafted", good["subject"], OBJ, "2026-11-10", [])
    assert t["gmail_draft_id"] is None and t["gmail_thread_id"] is None and t["body"].startswith("Dana,")


@pytest.mark.db
def test_run_draft_skips_a_suppressed_lead_and_marks_it_suppressed(world):
    db, bid, mbs = world
    db.table("suppression").insert({"domain": "glow0.com", "reason": "pytest"}).execute()
    good = {"subject": "Glow Med Spa / phone and DM booking", "body": GOOD, "objective": OBJ}
    assert run_draft(db, llm_returning(good), bid, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs}) == 1
    assert lead_row(db, 0)["status"] == "suppressed" and lead_row(db, 1)["status"] == "drafted"


@pytest.mark.db
def test_failed_draft_is_stored_held_with_problems(world):
    db, bid, mbs = world
    bad = {"subject": "x", "body": "nope", "objective": OBJ}
    assert run_draft(db, llm_returning(bad), bid, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs}) == 2
    assert lead_row(db, 0)["status"] == "drafted"
    t = db.table("touches").select("*").eq("lead_id", lead_row(db, 0)["id"]).execute().data[0]
    assert t["status"] == "held" and "too_short" in t["problems"] and t["gmail_draft_id"] is None and t["body"] == "nope"


@pytest.mark.db
def test_empty_model_answer_in_run_draft_is_held(world):
    db, bid, mbs = world
    assert run_draft(db, llm_returning({}), bid, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs}) == 2
    t = db.table("touches").select("*").eq("lead_id", lead_row(db, 0)["id"]).execute().data[0]
    assert t["status"] == "held" and t["body"] == "" and t["problems"]


def sent_touch1(db, lead_id, mailbox_id, sent_on):
    db.table("leads").update({"status": "sent", "mailbox_id": mailbox_id}).eq("id", lead_id).execute()
    db.table("touches").insert({"lead_id": lead_id, "touch_no": 1, "status": "sent", "subject": "Glow Med Spa / booking", "body": GOOD, "objective": OBJ,
                                "gmail_thread_id": "thread-1", "sent_at": f"{sent_on}T15:00:00+00:00", "scheduled_for": sent_on}).execute()


@pytest.mark.db
def test_followup_needs_no_gmail(world):
    db, bid, mbs = world
    lid = lead_row(db, 0)["id"]
    sent_touch1(db, lid, mbs[0]["id"], "2026-11-10")
    assert run_followups(db, date(2026, 11, 12)) == 0  # day 2: not due
    assert run_followups(db, date(2026, 11, 13)) == 1  # day 3
    t2 = db.table("touches").select("*").eq("lead_id", lid).eq("touch_no", 2).execute().data[0]
    assert t2["subject"] == "Re: Glow Med Spa / booking" and t2["scheduled_for"] == "2026-11-13" and "or is it not a priority?" in t2["body"]
    assert (t2["status"], t2["gmail_thread_id"], t2["gmail_draft_id"]) == ("drafted", "thread-1", None)
    assert run_followups(db, date(2026, 11, 13)) == 0  # not drafted twice
    db.table("touches").update({"status": "sent"}).eq("id", t2["id"]).execute()
    assert run_followups(db, date(2026, 11, 17)) == 1  # day 7 from Touch 1
    t3 = db.table("touches").select("*").eq("lead_id", lid).eq("touch_no", 3).execute().data[0]
    assert "partners" in t3["body"] and run_followups(db, date(2026, 12, 30)) == 0  # there is no Touch 4


@pytest.mark.db
def test_a_cancelled_touch_2_does_not_strand_touch_3(world):
    db, bid, mbs = world
    lid = lead_row(db, 0)["id"]
    sent_touch1(db, lid, mbs[0]["id"], "2026-11-10")
    assert run_followups(db, date(2026, 11, 13)) == 1
    db.table("touches").update({"status": "cancelled"}).eq("lead_id", lid).eq("touch_no", 2).execute()  # skipped by the owner
    assert run_followups(db, date(2026, 11, 17)) == 1
    assert db.table("touches").select("touch_no").eq("lead_id", lid).eq("touch_no", 3).execute().data


@pytest.mark.db
@pytest.mark.parametrize("stopper", ["replied", "bounced", "unsubscribed", "suppressed"])
def test_a_reply_bounce_or_opt_out_stops_the_sequence(world, stopper):
    db, bid, mbs = world
    lid = lead_row(db, 0)["id"]
    sent_touch1(db, lid, mbs[0]["id"], "2026-11-10")
    db.table("leads").update({"status": stopper}).eq("id", lid).execute()
    assert run_followups(db, date(2026, 11, 20)) == 0


@pytest.mark.db
def test_run_draft_says_why_a_lead_was_skipped(world, capsys):
    db, bid, mbs = world

    def boom(system, prompt):
        raise ValueError("vertex down")

    assert run_draft(db, boom, bid, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs}) == 0
    assert "skipped Glow Med Spa: ValueError: vertex down" in capsys.readouterr().err
    assert lead_row(db, 0)["status"] == "selected"


BATCH_NO = 987001  # no real batch carries this number


@pytest.mark.db
def test_draft_by_batch_no_takes_approved_selected_leads_across_source_batches(world):
    db, bid, mbs = world
    assert not db.table("leads").select("id").eq("batch_no", BATCH_NO).execute().data  # a real lead here would be drafted too
    bid2 = new_batch(db, "B", "TX", ["x"])
    try:
        item = {"placeId": "TEST_3", "title": "Glow Med Spa", "website": "https://glow3.com", "categories": ["Medical spa"], "state": "Texas"}
        db.table("leads").insert({**place_to_lead(item, bid2), "status": "selected", "approved": True, "owner_name": "Dana W", "owner_title": "Owner",
                                  "owner_email": "dana@glow3.com", "email_verified": True, "vector": "capacity", "signal_led": False, "signal": LEAD["signal"]}).execute()
        for i in (0, 2, 3):  # TEST_0 and TEST_3 approved in two source batches; TEST_2 not approved; TEST_1 approved but in no outreach batch
            db.table("leads").update({"batch_no": BATCH_NO}).eq("place_id", f"TEST_{i}").execute()
        good = {"subject": "Glow Med Spa / phone and DM booking", "body": GOOD, "objective": OBJ}
        llm = llm_returning(good)
        n = run_draft(db, llm, None, date(2026, 11, 10), only_mailboxes={m["id"] for m in mbs}, batch_no=BATCH_NO)
        assert n == 2 and len(llm.calls) == 2
        assert [lead_row(db, i)["status"] for i in range(4)] == ["drafted", "selected", "selected", "drafted"]
    finally:
        db.table("leads").delete().like("place_id", "TEST_%").execute()
        db.table("batches").delete().eq("id", bid2).execute()


def test_run_draft_needs_exactly_one_of_batch_id_and_batch_no():
    for args in ({"batch_id": "b1", "batch_no": 3}, {"batch_id": None}):
        with pytest.raises(ValueError):
            run_draft(None, None, today=date(2026, 11, 10), **args)


def test_check_subject_applies_to_touch_1_only():
    assert check_subject("Glow Med Spa / booking", 1) == [] and check_subject("Quick hello", 1) == ["bad_subject"] and check_subject("", 1) == ["bad_subject"]
    assert check_subject("Re: Glow Med Spa", 2) == []


def test_strip_footer_removes_a_configured_footer_only(monkeypatch):
    monkeypatch.setattr("gtm.draft.get_settings", lambda: Settings.from_env({"OPT_OUT_LINE": "Reply stop."}))
    assert strip_footer("Hi\n\nSoban\n\nReply stop.") == "Hi\n\nSoban" and strip_footer("Hi\n\nSoban") == "Hi\n\nSoban"
    monkeypatch.setattr("gtm.draft.get_settings", lambda: Settings.from_env({}))
    assert strip_footer("Hi\n\nSoban") == "Hi\n\nSoban"
