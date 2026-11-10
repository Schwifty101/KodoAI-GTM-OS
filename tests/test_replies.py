import pytest

from support import purge_test_suppression
from gtm.db import get_db
from gtm.replies import apply_reply, classify_reply, new_text, run_replies
from gtm.scrape import new_batch, place_to_lead


def msg(body, subject="Re: Glow Med Spa / booking", frm="Dana <dana@glow0.com>", **headers):
    return {"from": frm, "subject": subject, "headers": {k.lower().replace("_", "-"): v for k, v in headers.items()}, "body": body}


def llm_says(kind):
    return lambda system, prompt: {"kind": kind}


@pytest.mark.parametrize("m", [
    msg("Thanks!", Auto_Submitted="auto-replied"),
    msg("Thanks!", Auto_Submitted="auto-generated"),
    msg("Thanks!", Precedence="auto_reply"),
    msg("Thanks!", X_Autoreply="yes"),
    msg("I am away.", subject="Automatic reply: Glow Med Spa / booking"),
    msg("Hi, I am out of the office until Monday and will reply when I return."),
    msg("Thank you for your email. I am currently out of the office."),
])
def test_out_of_office_and_auto_replies_are_auto_reply(m):
    assert classify_reply(m, llm=lambda s, p: pytest.fail("rules decide this, not the model")) == "auto_reply"


@pytest.mark.parametrize("text", [
    "please take me off your list", "Stop emailing me.", "unsubscribe", "Please remove me from your list.", "Do not contact me again.",
    "I'd like to opt out", "not interested, stop contacting us", "Don't email me again",
])
def test_free_text_opt_outs_are_opt_out(text):
    assert classify_reply(msg(text), llm=lambda s, p: pytest.fail("rules decide this")) == "opt_out"


def test_auto_reply_that_mentions_unsubscribe_is_still_an_auto_reply():
    assert classify_reply(msg("Newsletter footer: unsubscribe here", Auto_Submitted="auto-replied")) == "auto_reply"


def test_our_own_quoted_opt_out_line_is_not_an_opt_out():
    body = "Sounds interesting, tell me more.\n\nOn Mon, Nov 9, 2026 at 9:00 AM Soban <soban@kodoai.xyz> wrote:\n> Reply stop to opt out.\n> Soban"
    assert new_text(body) == "Sounds interesting, tell me more."
    assert classify_reply(msg(body), llm=llm_says("positive")) == "positive"


@pytest.mark.parametrize("frm,subject", [
    ("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification (Failure)"),
    ("postmaster@glow0.com", "Undeliverable: Glow Med Spa / booking"),
])
def test_bounce_notices_are_bounce(frm, subject):
    assert classify_reply(msg("550 No such user", subject=subject, frm=frm)) == "bounce"


@pytest.mark.parametrize("kind", ["positive", "negative", "other"])
def test_the_model_decides_between_positive_negative_and_other(kind):
    assert classify_reply(msg("Tell me more about what you build."), llm=llm_says(kind)) == kind


def test_anything_unclear_or_failing_is_other():
    assert classify_reply(msg("hmm")) == "other"
    assert classify_reply(msg("hmm"), llm=llm_says("great")) == "other"

    def boom(s, p):
        raise RuntimeError("down")

    assert classify_reply(msg("hmm"), llm=boom) == "other"


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    mb = db.table("mailboxes").insert({"address": "pytest-rep@example.com", "daily_cap": 40, "enabled_on": "2026-01-01"}).execute().data[0]
    items = [{"placeId": f"TEST_{i}", "title": f"Spa {i}", "website": f"https://glow{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(3)]
    leads = db.table("leads").insert([{**place_to_lead(it, bid), "status": "sent", "owner_email": f"dana@glow{i}.com", "owner_name": "Dana W", "email_verified": True,
                                       "mailbox_id": mb["id"]} for i, it in enumerate(items)]).execute().data
    for i, l in enumerate(leads):
        db.table("touches").insert([{"lead_id": l["id"], "touch_no": 1, "status": "sent", "gmail_thread_id": f"thread-{i}", "sent_at": "2026-11-10T15:00:00+00:00"},
                                    {"lead_id": l["id"], "touch_no": 2, "status": "drafted", "scheduled_for": "2026-11-13"}]).execute()
    yield db, leads, mb
    db.table("suppression").delete().like("reason", "pytest%").execute()
    purge_test_suppression(db)
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("mailboxes").delete().like("address", "pytest-rep%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def state(db, lead):
    l = db.table("leads").select("status").eq("id", lead["id"]).execute().data[0]["status"]
    ts = {t["touch_no"]: t for t in db.table("touches").select("*").eq("lead_id", lead["id"]).execute().data}
    return l, ts


@pytest.mark.db
def test_opt_out_suppresses_address_and_business_domain_and_cancels_touches(world):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], "opt_out")
    status, ts = state(db, leads[0])
    assert status == "unsubscribed" and ts[2]["status"] == "cancelled" and ts[1]["outcome"] == "opt_out"
    rows = db.table("suppression").select("*").eq("reason", "opt-out reply").execute().data
    assert {(r["email"], r["domain"]) for r in rows} == {("dana@glow0.com", None), (None, "glow0.com")}


@pytest.mark.db
def test_opt_out_never_suppresses_a_free_mail_domain(world):
    db, leads, _ = world
    db.table("leads").update({"domain": "gmail.com", "owner_email": "dana@gmail.com"}).eq("id", leads[0]["id"]).execute()
    apply_reply(db, leads[0]["id"], "opt_out")
    domains = [r["domain"] for r in db.table("suppression").select("domain").eq("reason", "opt-out reply").execute().data if r["domain"]]
    assert domains == []  # the address is suppressed, gmail.com is not


@pytest.mark.db
def test_bounce_sets_bounced_cancels_touches_and_suppresses_only_the_address(world):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], "bounce")
    status, ts = state(db, leads[0])
    assert status == "bounced" and ts[2]["status"] == "cancelled"
    rows = db.table("suppression").select("*").eq("reason", "bounce").execute().data
    assert [(r["email"], r["domain"]) for r in rows] == [("dana@glow0.com", None)]


@pytest.mark.db
@pytest.mark.parametrize("kind", ["positive", "negative", "other"])
def test_a_real_reply_marks_replied_and_stops_the_sequence(world, kind):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], kind)
    status, ts = state(db, leads[0])
    assert status == "replied" and ts[2]["status"] == "cancelled" and ts[1]["outcome"] == kind


@pytest.mark.db
def test_an_auto_reply_changes_nothing(world):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], "auto_reply")
    status, ts = state(db, leads[0])
    assert status == "sent" and ts[2]["status"] == "drafted" and ts[1].get("outcome") is None


@pytest.mark.db
def test_run_replies_reads_threads_ignores_our_own_messages_and_applies_the_result(world):
    db, leads, mb = world
    own = msg("Is easier booking something you're working on?", frm="Soban <pytest-rep@example.com>")
    threads = {"thread-0": [own, msg("please remove me")], "thread-1": [own, msg("Thanks", Auto_Submitted="auto-replied")], "thread-2": [own]}
    bounce = {"from": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "subject": "Delivery Status Notification (Failure)", "headers": {}, "body": "dana@glow2.com not found"}
    out = run_replies(db, lambda addr: object(), lambda s, p: {"kind": "other"}, thread_messages=lambda svc, tid: threads[tid], recent_bounces=lambda svc: [bounce])
    assert out == {"opt_out": 1, "auto_reply": 1, "bounce": 1}
    assert state(db, leads[0])[0] == "unsubscribed" and state(db, leads[1])[0] == "sent" and state(db, leads[2])[0] == "bounced"


@pytest.mark.parametrize("text", [
    "Just back from being on vacation, please take me off your list.",
    "I was out of the office last week. Stop emailing me.",
    "I am currently away but I do not want these emails, please unsubscribe me.",
])
def test_an_opt_out_that_mentions_being_away_is_still_an_opt_out(text):
    assert classify_reply(msg(text), llm=lambda s, p: pytest.fail("rules decide this")) == "opt_out"


@pytest.mark.db
def test_run_replies_considers_every_inbound_message_and_opt_out_wins_over_a_later_auto_reply(world):
    db, leads, mb = world
    own = msg("Is easier booking something you're working on?", frm="Soban <pytest-rep@example.com>")
    ooo = msg("I am out of the office until Monday.", Auto_Submitted="auto-replied")
    threads = {"thread-0": [own, msg("please remove me"), ooo], "thread-1": [own], "thread-2": [own]}
    out = run_replies(db, lambda addr: object(), lambda s, p: {"kind": "other"}, thread_messages=lambda svc, tid: threads[tid], recent_bounces=lambda svc: [])
    assert out == {"opt_out": 1} and state(db, leads[0])[0] == "unsubscribed"


@pytest.mark.db
def test_run_replies_reads_the_threads_of_every_sent_touch_not_just_the_latest(world):
    db, leads, mb = world
    db.table("touches").update({"status": "sent", "gmail_thread_id": "thread-new", "sent_at": "2026-11-13T15:00:00+00:00"}).eq("lead_id", leads[0]["id"]).eq("touch_no", 2).execute()
    own = msg("Hi", frm="Soban <pytest-rep@example.com>")
    threads = {"thread-0": [own, msg("stop emailing me")], "thread-new": [own], "thread-1": [own], "thread-2": [own]}
    out = run_replies(db, lambda addr: object(), lambda s, p: {"kind": "other"}, thread_messages=lambda svc, tid: threads[tid], recent_bounces=lambda svc: [])
    assert out == {"opt_out": 1} and state(db, leads[0])[0] == "unsubscribed"
