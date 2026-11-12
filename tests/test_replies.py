import pytest

from support import purge_test_suppression
from gtm.db import get_db
from gtm.replies import apply_reply, classify_reply, local_kind, new_text, run_replies
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
    assert classify_reply(msg("Who are you and what do you build?"), llm=llm_says(kind)) == kind


def test_anything_unclear_or_failing_is_other():
    assert classify_reply(msg("hmm")) == "other"
    assert classify_reply(msg("hmm"), llm=llm_says("great")) == "other"

    def boom(s, p):
        raise RuntimeError("down")

    assert classify_reply(msg("hmm"), llm=boom) == "other"


@pytest.mark.parametrize("text", ["Not interested, thanks.", "No thank you", "we're all set", "We are covered.", "No.", "no", "I am not interested", "We already have a provider", "Not interested.\n\nSent from my iPhone", "I'm not interested", "we are not interested", "No thank you!",
                                  "Hi, no thanks", "Hello Soban, not interested, thanks", "Not interested, sorry", "We're all set", "We're good, thanks"])
def test_local_negative(text):
    assert local_kind(text) == "negative"


@pytest.mark.parametrize("text", ["Sounds good, tell me more", "Yes please", "yes", "What's the pricing?", "Let's schedule a call", "I'm interested", "Send me more info", "no problem, send details"])
def test_local_positive(text):
    assert local_kind(text) == "positive"


@pytest.mark.parametrize("text", ["Not right now, maybe next quarter", "not sure if we're interested", "Who are you?", "Please send details but we are not interested",
                                  "No thanks, can you explain what this is?", "hmm", "Circle back later, sounds good",
                                  "Not interested in that, but I would love to hear about your capacity tool", "Sure, no need to call, just email me pricing",
                                  "We already have a provider but we're unhappy with them", "Not a fit for the owner, but talk to my manager Dana", "Please don't hesitate to call",
                                  "no need to apologize, I'd love to see a demo", "No need for a call, can you send a one pager", "not looking forward to another tool but intrigued",
                                  "We're good on that front, but I'd love to learn about the booking piece", "We're good on that front. Forward this to dana@x.com she handles it",
                                  "Not interested personally, my partner Jen handles marketing: jen@x.com", "Thanks! not for us, but my friend runs a spa, can I refer her",
                                  "Not interested in Botox marketing, we need help with front desk calls", "we've been looking for something like this, not interested in contracts though",
                                  "We are covered for now, but happy to chat in the spring", "Not interested at this time", "Not interested at the moment", "Not interested this year",
                                  "Not interested, try us in 6 months", "No thanks for now", "we're good for now", "Not a fit yet, we open our second location in spring",
                                  "I know", "note", "innovation",
                                  "Not interested in a call. Email works", "Not interested in the call, email works", "we're covered at this location, not the other one",
                                  "Not for us at the other location", "No thanks. Try the Austin location", "not interested - talk to Dana",
                                  "We are all set on that. Reach Maria at the other clinic", "Not for us, try Glow Med Spa down the street",
                                  "No thanks, we have two other locations you could email", "Not interested in that, ask about lasers",
                                  "Not interested in that service, what else do you do", "Not interested unless it's free", "Not interested until Q3", "No thanks, busy season",
                                  "We're good for the time being", "Not interested right now", "Not looking to switch our software", "Not interested in AI", "Not interested in Botox",
                                  "We are good, thanks! Actually yes tell me more", "Thank you for reaching out but we are not interested in this at all so please stop"])
def test_local_unsure_falls_through(text):
    assert local_kind(text) is None


@pytest.mark.parametrize("text,kind", [("Not interested, thanks.", "negative"), ("Sounds good, tell me more", "positive")])
def test_clear_replies_never_call_the_model(text, kind):
    assert classify_reply(msg(text), llm=lambda s, p: pytest.fail("local rules decide this")) == kind


def test_dont_call_me_is_an_opt_out_and_dont_hesitate_is_not():
    assert classify_reply(msg("Don't call me"), llm=lambda s, p: pytest.fail("rules decide this")) == "opt_out"
    assert classify_reply(msg("Please don't hesitate to call"), llm=llm_says("other")) == "other"


def test_a_bare_decline_skips_the_model_but_a_decline_with_more_in_it_does_not():
    calls = []

    def llm(system, prompt):
        calls.append(prompt)
        return {"kind": "other"}

    assert classify_reply(msg("No thanks"), llm=llm) == "negative" and calls == []
    assert classify_reply(msg("Not interested in a call. Email works"), llm=llm) == "other" and len(calls) == 1


def test_unsure_replies_do_call_the_model():
    assert classify_reply(msg("Not right now, maybe next quarter"), llm=llm_says("other")) == "other"
    assert classify_reply(msg("Who are you?"), llm=llm_says("negative")) == "negative"


@pytest.mark.db
def test_classification_cost_carries_the_lead(world):
    from gtm.costs import log_cost

    db, leads, _ = world
    own = msg("Hi", frm="Soban <pytest-rep@example.com>")
    threads = {"thread-0": [own, msg("Who are you?")], "thread-1": [own], "thread-2": [own]}

    def llm(system, prompt):
        log_cost("gemini", 1, None, note="pytest-classify")
        return {"kind": "other"}

    try:
        run_replies(db, lambda addr: object(), llm, thread_messages=lambda svc, tid: threads[tid], recent_bounces=lambda svc: [])
        got = db.table("cost_log").select("lead_id").eq("note", "pytest-classify").execute().data
        assert [g["lead_id"] for g in got] == [leads[0]["id"]]
    finally:
        db.table("cost_log").delete().eq("note", "pytest-classify").execute()


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


@pytest.mark.db
def test_negative_reply_suppresses_like_an_opt_out_but_keeps_replied(world):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], "negative", "dana@glow0.com")
    assert state(db, leads[0])[0] == "replied"
    rows = db.table("suppression").select("*").eq("reason", "not-interested").in_("email", ["dana@glow0.com"]).execute().data
    dom = db.table("suppression").select("*").eq("reason", "not-interested").eq("domain", "glow0.com").execute().data
    assert len(rows) == 1 and len(dom) == 1


@pytest.mark.db
def test_positive_reply_adds_no_suppression(world):
    db, leads, _ = world
    apply_reply(db, leads[0]["id"], "positive", "dana@glow0.com")
    assert db.table("suppression").select("id").in_("email", ["dana@glow0.com"]).execute().data == []


@pytest.mark.db
def test_a_later_positive_in_the_thread_beats_an_earlier_negative(world):
    db, leads, _ = world
    own = msg("Hi", frm="Soban <pytest-rep@example.com>")
    threads = {"thread-0": [own, msg("not interested"), msg("actually tell me more")], "thread-1": [own], "thread-2": [own]}
    out = run_replies(db, lambda addr: object(), lambda s, p: pytest.fail("local"), thread_messages=lambda svc, tid: threads[tid], recent_bounces=lambda svc: [])
    assert out == {"positive": 1} and state(db, leads[0])[0] == "replied"
    assert db.table("suppression").select("id").eq("reason", "not-interested").in_("email", ["dana@glow0.com"]).execute().data == []
