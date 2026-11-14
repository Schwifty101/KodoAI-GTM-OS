from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from support import purge_test_suppression
from gtm.config import Settings
from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead
from gtm.send import allowance, in_window, send_due, send_with_reply_check, should_pause

TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)  # Tuesday 12:00 in Texas, inside the window
SETTINGS = Settings.from_env({"RAMP_START": "2", "RAMP_STEP": "1", "DAILY_CAP": "40", "PAUSE_BOUNCE_RATE": "0.03", "PAUSE_MIN_SENDS": "20"})


def test_allowance_ramps_then_caps():
    mb = {"enabled_on": "2026-11-10"}
    got = [allowance(mb, TODAY + timedelta(days=n), 10, 5, 40) for n in (0, 1, 2, 6, 7, 30)]
    assert got == [10, 15, 20, 40, 40, 40]


def test_allowance_is_zero_before_the_mailbox_is_enabled_or_when_never_enabled():
    assert allowance({"enabled_on": "2026-11-11"}, TODAY, 10, 5, 40) == 0
    assert allowance({"enabled_on": None}, TODAY, 10, 5, 40) == 0


def test_a_lower_per_mailbox_cap_wins():
    assert allowance({"enabled_on": "2026-01-01"}, TODAY, 10, 5, 25) == 25


@pytest.mark.parametrize("sent,bounced,complaints,expected", [
    (100, 2, 0, False),   # 2%
    (100, 4, 0, True),    # 4% is over 3%
    (10, 5, 0, False),    # too few sends to judge a rate
    (10, 0, 1, True),     # any complaint pauses, however few sends
    (0, 0, 0, False),
])
def test_should_pause(sent, bounced, complaints, expected):
    assert should_pause(sent, bounced, complaints, rate=0.03, min_sends=20) is expected


@pytest.mark.parametrize("utc,tz,ok", [
    (datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc), "America/Chicago", True),      # Tue 12:00 local
    (datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc), "America/Chicago", False),     # Saturday
    (datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc), "America/Chicago", False),     # Tue 07:00 local, too early
    (datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc), "America/Chicago", False),     # Tue 17:00 local, too late
    (datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc), "America/Los_Angeles", True),  # same instant is 15:00 in LA
    (datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc), None, True),                   # null tz falls back to Chicago (09:00)
    (datetime(2026, 11, 10, 14, 59, tzinfo=timezone.utc), None, False),                 # Chicago 08:59
])
def test_in_window(utc, tz, ok):
    assert in_window(utc, tz) is ok


@pytest.mark.db
def test_outside_the_window_the_draft_stays_drafted_and_sends_later(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, tz="America/Chicago")
    gm = Gmail()
    saturday = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, saturday)
    assert out.get("sent", 0) == 0 and out["deferred"] == 1 and gm.sent == [] and touch(db, l["id"])["status"] == "drafted"
    assert send_due(db, lambda addr: gm, TODAY, SETTINGS, saturday, anytime=True)["sent"] == 1  # --anytime ignores the window
    (l2,) = make_leads(db, bid, mb, 1, offset=5, tz="America/Chicago")
    assert send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)["sent"] == 1  # inside the window it sends


def test_sending_lives_only_in_send_py_so_drafting_can_never_send():
    assert "send_draft" not in Path("gtm/draft.py").read_text()


class Gmail:
    def __init__(self):
        self.sent = []

    def users(self):
        return self

    def drafts(self):
        return self

    def send(self, **kw):
        self.sent.append(kw["body"]["id"])
        return type("E", (), {"execute": lambda s: {"id": "m", "threadId": f"thread-{kw['body']['id']}"}})()


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    mb = db.table("mailboxes").insert({"address": "pytest-send@example.com", "daily_cap": 40, "enabled_on": TODAY.isoformat()}).execute().data[0]
    yield db, bid, mb
    db.table("suppression").delete().like("reason", "pytest%").execute()
    purge_test_suppression(db)  # written by apply_reply in the reply-check test; only the tests' own addresses
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("mailboxes").delete().like("address", "pytest-send%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def make_leads(db, bid, mb, n, status="drafted", touch_no=1, touch_status="drafted", offset=0, **lead_kw):
    items = [{"placeId": f"TEST_{offset + i:03d}", "title": f"Spa {i}", "website": f"https://glow{offset + i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(n)]
    rows = [{**place_to_lead(it, bid), "status": status, "owner_name": "Dana W", "owner_email": f"dana@glow{offset + i}.com", "email_verified": True,
             "mailbox_id": mb["id"], **lead_kw} for i, it in enumerate(items)]
    leads = db.table("leads").insert(rows).execute().data
    db.table("touches").insert([{"lead_id": l["id"], "touch_no": touch_no, "status": touch_status, "gmail_draft_id": f"d{l['place_id']}", "subject": "s", "body": "b",
                                 "scheduled_for": TODAY.isoformat()} for l in leads]).execute()
    return leads


def touch(db, lead_id, n=1):
    return db.table("touches").select("*").eq("lead_id", lead_id).eq("touch_no", n).execute().data[0]


def lead(db, lead_id):
    return db.table("leads").select("*").eq("id", lead_id).execute().data[0]


@pytest.mark.db
def test_send_sends_the_draft_records_thread_and_marks_lead_sent(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1)
    gm = Gmail()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    t = touch(db, l["id"])
    assert out["sent"] == 1 and gm.sent == [t["gmail_draft_id"]]
    assert t["status"] == "sent" and t["gmail_thread_id"] == f"thread-{t['gmail_draft_id']}" and t["sent_at"]
    assert lead(db, l["id"])["status"] == "sent"


@pytest.mark.db
def test_cap_reached_mid_batch_leaves_the_rest_drafted(world):
    db, bid, mb = world
    leads = make_leads(db, bid, mb, 3)
    gm = Gmail()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)  # day 0 allowance = ramp_start = 2
    assert out["sent"] == 2 and len(gm.sent) == 2
    assert sorted(touch(db, l["id"])["status"] for l in leads) == ["drafted", "sent", "sent"]
    assert send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW).get("sent", 0) == 0  # the same day's allowance is already used


@pytest.mark.db
def test_paused_mailbox_sends_nothing_until_cleared(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1)
    db.table("mailboxes").update({"paused": True, "paused_reason": "pytest"}).eq("id", mb["id"]).execute()
    gm = Gmail()
    assert send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW).get("sent", 0) == 0 and gm.sent == []
    db.table("mailboxes").update({"paused": False}).eq("id", mb["id"]).execute()
    assert send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)["sent"] == 1


@pytest.mark.db
def test_a_bounce_spike_pauses_the_mailbox_and_sends_nothing(world):
    db, bid, mb = world
    old = datetime.combine(TODAY - timedelta(days=2), time(12), tzinfo=timezone.utc).isoformat()
    history = make_leads(db, bid, mb, 25, status="sent", touch_status="sent", offset=100)
    for i, l in enumerate(history):
        db.table("touches").update({"sent_at": old}).eq("lead_id", l["id"]).execute()
        if i < 5:  # 5 of 25 bounced = 20%
            db.table("leads").update({"status": "bounced"}).eq("id", l["id"]).execute()
    (due,) = make_leads(db, bid, mb, 1, offset=0)
    gm = Gmail()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    row = db.table("mailboxes").select("*").eq("id", mb["id"]).execute().data[0]
    assert out.get("sent", 0) == 0 and gm.sent == [] and row["paused"] is True and "bounce" in row["paused_reason"]
    assert touch(db, due["id"])["status"] == "drafted"


@pytest.mark.db
def test_suppressed_lead_is_not_sent_even_if_drafted(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1)
    db.table("suppression").insert({"domain": "glow0.com", "reason": "pytest"}).execute()
    gm = Gmail()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    assert gm.sent == [] and out["cancelled"] == 1
    assert touch(db, l["id"])["status"] == "cancelled" and lead(db, l["id"])["status"] == "suppressed"


@pytest.mark.db
@pytest.mark.parametrize("stopper", ["replied", "bounced", "unsubscribed", "suppressed", "booked"])
def test_reply_or_bounce_cancels_later_touches(world, stopper):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, status=stopper, touch_no=2)
    gm = Gmail()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    assert gm.sent == [] and out["cancelled"] == 1 and touch(db, l["id"], 2)["status"] == "cancelled"


@pytest.mark.db
def test_touch_1_to_a_company_we_already_emailed_is_held_not_sent(world):
    db, bid, mb = world
    (a,) = make_leads(db, bid, mb, 1, status="sent", touch_status="sent", offset=0)
    (b,) = make_leads(db, bid, mb, 1, offset=1)  # a different place...
    db.table("leads").update({"domain": "glow0.com", "owner_email": "other@glow0.com"}).eq("id", b["id"]).execute()  # ...at the same company
    gm = Gmail()
    send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    assert gm.sent == [] and touch(db, b["id"])["status"] == "drafted"


@pytest.mark.db
def test_follow_ups_go_out_before_new_leads_when_the_allowance_is_short(world):
    db, bid, mb = world
    new = make_leads(db, bid, mb, 2, offset=0)
    (fu,) = make_leads(db, bid, mb, 1, status="sent", touch_no=2, offset=50)
    gm = Gmail()
    send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)  # allowance 2
    assert touch(db, fu["id"], 2)["status"] == "sent"
    assert sorted(touch(db, l["id"])["status"] for l in new) == ["drafted", "sent"]


@pytest.mark.db
def test_a_gmail_error_leaves_the_draft_unsent_and_the_run_going(world):
    db, bid, mb = world
    leads = make_leads(db, bid, mb, 2)

    class Flaky(Gmail):
        def send(self, **kw):
            if not self.sent and not hasattr(self, "tried"):
                self.tried = True
                raise RuntimeError("quota")
            return super().send(**kw)

    gm = Flaky()
    out = send_due(db, lambda addr: gm, TODAY, SETTINGS, NOW)
    assert out["errors"] == 1 and out["sent"] == 1
    assert sorted(touch(db, l["id"])["status"] for l in leads) == ["drafted", "sent"]


@pytest.mark.db
def test_send_with_reply_check_reads_replies_first_so_a_stopped_lead_gets_no_follow_up(world):
    """Anti-goal: emailing after an opt-out. The lead is still `sent` in the database until replies are read."""
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, status="sent", touch_no=2)
    db.table("touches").insert({"lead_id": l["id"], "touch_no": 1, "status": "sent", "gmail_thread_id": "thread-1", "sent_at": "2026-11-10T12:00:00+00:00"}).execute()
    gm = Gmail()
    inbox = {"thread-1": [{"from": "Dana <dana@glow0.com>", "subject": "Re: s", "headers": {}, "body": "Please stop emailing me."}]}
    out = send_with_reply_check(db, lambda addr: gm, lambda s, p: {"kind": "other"}, TODAY, SETTINGS, now=NOW,
                                thread_messages=lambda svc, tid: inbox[tid], recent_bounces=lambda svc: [])
    assert gm.sent == [] and out["replies"] == {"opt_out": 1}
    assert touch(db, l["id"], 2)["status"] == "cancelled" and lead(db, l["id"])["status"] == "unsubscribed"
