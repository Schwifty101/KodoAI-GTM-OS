from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import base64
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from support import purge_test_suppression
from gtm.config import Settings
from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead
from gtm.send import allowance, in_window, is_test_lead, pick_send_at, schedule_approved, send_scheduled, send_tick, sending_days, should_pause, window_end

TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)  # Tuesday 12:00 in Texas, inside the window
SETTINGS = Settings.from_env({"RAMP_START": "2", "RAMP_STEP": "1", "DAILY_CAP": "40", "PAUSE_BOUNCE_RATE": "0.03", "PAUSE_MIN_SENDS": "20"})


def test_allowance_ramps_by_sending_days_then_caps():
    mb = {"enabled_on": "2026-11-10", "paused": False}
    assert [allowance(mb, n, 20, 3, 40) for n in (0, 1, 2, 6, 7, 30)] == [20, 23, 26, 38, 40, 40]


def test_allowance_is_zero_when_never_enabled_or_paused():
    assert allowance({"enabled_on": None, "paused": False}, 5, 20, 3, 40) == 0
    assert allowance({"enabled_on": "2026-11-10", "paused": True}, 5, 20, 3, 40) == 0


def test_a_lower_per_mailbox_cap_wins():
    assert allowance({"enabled_on": "2026-01-01", "paused": False}, 30, 10, 5, 25) == 25


def test_is_test_lead_prefixes():
    assert is_test_lead("TEST_001") and is_test_lead("REHEARSAL_B_1") and not is_test_lead("ChIJabc")


def _sent_days(db, bid, mb, days, prefix="PYB_", offset=0):
    for k, d in enumerate(days):
        at = datetime.combine(TODAY - timedelta(days=d), time(12), tzinfo=timezone.utc).isoformat()
        make_leads(db, bid, mb, 1, status="sent", touch_status="sent", offset=offset + k, prefix=prefix, sent_at=at)


@pytest.mark.db
def test_first_real_send_day_allows_ramp_start(world):
    db, bid, mb = world
    assert allowance(mb, sending_days(db, mb["id"], TODAY), 20, 3, 40) == 20


@pytest.mark.db
def test_second_sending_day_allows_23(world):
    db, bid, mb = world
    _sent_days(db, bid, mb, [1])
    assert allowance(mb, sending_days(db, mb["id"], TODAY), 20, 3, 40) == 23


@pytest.mark.db
def test_a_gap_day_does_not_advance_the_ramp(world):
    db, bid, mb = world
    _sent_days(db, bid, mb, [3, 1, 1], offset=0)  # two sending days with a gap, two sends on one of them
    assert sending_days(db, mb["id"], TODAY) == 2


@pytest.mark.db
def test_today_and_later_sends_are_not_counted(world):
    db, bid, mb = world
    _sent_days(db, bid, mb, [0])
    assert sending_days(db, mb["id"], TODAY) == 0


@pytest.mark.db
def test_rehearsal_sends_do_not_advance_the_ramp(world):
    db, bid, mb = world
    _sent_days(db, bid, mb, [2], prefix="TEST_")
    _sent_days(db, bid, mb, [1], prefix="REHEARSAL_B_", offset=5)
    assert sending_days(db, mb["id"], TODAY) == 0


@pytest.mark.db
def test_ramp_restarts_after_ramp_from(world):
    db, bid, mb = world
    _sent_days(db, bid, mb, [5, 4, 1])
    db.table("mailboxes").update({"ramp_from": (TODAY - timedelta(days=2)).isoformat()}).eq("id", mb["id"]).execute()
    assert sending_days(db, mb["id"], TODAY) == 1


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


@pytest.mark.parametrize("tz", [None, "America/Chicago", "America/Los_Angeles", "America/New_York"])
@pytest.mark.parametrize("now", [
    datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc),  # Tue 09:00 Chicago, the first minute of the window
    datetime(2026, 11, 10, 21, 59, tzinfo=timezone.utc),  # Tue 15:59 Chicago, the last minute
    datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc),    # Mon after the DST end (Nov 1)
    datetime(2026, 3, 9, 18, 0, tzinfo=timezone.utc),     # Mon after the DST start (Mar 8)
])
def test_every_send_at_is_inside_the_leads_window(now, tz):
    for seed in range(50):
        at = pick_send_at(now, tz, random.Random(seed))
        if in_window(now, tz):
            assert now <= at < window_end(now, tz) and in_window(at, tz)
        else:
            assert at is None


def test_sixteen_oclock_edge_is_excluded():
    four = datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)  # Tue 16:00 Chicago
    assert pick_send_at(four, "America/Chicago", random.Random(1)) is None
    assert pick_send_at(four - timedelta(minutes=1), "America/Chicago", random.Random(1)) < four


def test_null_tz_window_ends_at_sixteen_chicago():
    assert window_end(NOW, None) == datetime(2026, 11, 10, 22, 0, tzinfo=timezone.utc)


def _status(db, lead_id, n=1):
    return touch(db, lead_id, n)["status"]


@pytest.mark.db
def test_follow_ups_are_scheduled_before_new_leads(world):
    db, bid, mb = world
    new = make_leads(db, bid, mb, 2, touch_status="approved", tkw={"approved_at": "2026-11-10T10:00:00+00:00"})
    (fu,) = make_leads(db, bid, mb, 1, status="sent", touch_no=2, touch_status="approved", offset=50)
    assert schedule_approved(db, mb, NOW, SETTINGS, random.Random(1)) == 2  # allowance 2
    assert _status(db, fu["id"], 2) == "scheduled" and touch(db, fu["id"], 2)["send_at"]
    assert sorted(_status(db, l["id"]) for l in new) == ["approved", "scheduled"]


@pytest.mark.db
def test_stranded_sending_counts_against_room(world):
    db, bid, mb = world
    make_leads(db, bid, mb, 1, touch_status="sending", offset=60)
    fresh = make_leads(db, bid, mb, 2, touch_status="approved")
    assert schedule_approved(db, mb, NOW, SETTINGS, random.Random(1)) == 1
    assert sorted(_status(db, l["id"]) for l in fresh) == ["approved", "scheduled"]


@pytest.mark.db
def test_outside_window_stays_approved_unless_anytime(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="approved", tz="America/Chicago")
    saturday = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    assert schedule_approved(db, mb, saturday, SETTINGS, random.Random(1)) == 0 and _status(db, l["id"]) == "approved"
    assert schedule_approved(db, mb, saturday, SETTINGS, random.Random(1), anytime=True) == 1


@pytest.mark.db
def test_stopped_and_blocked_leads_are_not_scheduled(world):
    db, bid, mb = world
    (a,) = make_leads(db, bid, mb, 1, status="replied", touch_status="approved", offset=70)
    (b,) = make_leads(db, bid, mb, 1, touch_status="approved", offset=71)
    db.table("suppression").insert({"domain": "glow71.com", "reason": "pytest"}).execute()
    assert schedule_approved(db, mb, NOW, SETTINGS, random.Random(1)) == 0
    assert _status(db, a["id"]) == "approved" and _status(db, b["id"]) == "approved"


PAST = "2026-11-10T17:00:00+00:00"  # an hour before NOW


def _go(db, gm, mb, **kw):
    return send_scheduled(db, lambda addr: gm, mb, NOW, SETTINGS, **kw)


@pytest.mark.db
def test_touch_1_is_created_sent_and_marks_the_lead_sent(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    gm = Gmail()
    assert _go(db, gm, mb)["sent"] == 1 and gm.sent == ["draft1"]
    t = touch(db, l["id"])
    assert t["status"] == "sent" and t["sent_at"] and t["gmail_thread_id"] == "thread-draft1" and lead(db, l["id"])["status"] == "sent"
    assert "threadId" not in gm.created[0]


@pytest.mark.db
def test_send_once_under_two_concurrent_claims(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    gm = Gmail()
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda _: send_scheduled(get_db(), lambda addr: gm, mb, NOW, SETTINGS), range(2)))
    assert gm.sent == ["draft1"] and len(gm.created) == 1 and touch(db, l["id"])["status"] == "sent"


@pytest.mark.db
@pytest.mark.parametrize("stopper", ["replied", "bounced", "unsubscribed", "suppressed", "booked"])
def test_a_stopped_lead_is_cancelled_not_sent(world, stopper):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, status=stopper, touch_status="scheduled", tkw={"send_at": PAST})
    gm = Gmail()
    assert _go(db, gm, mb)["cancelled"] == 1 and gm.sent == [] and gm.created == [] and touch(db, l["id"])["status"] == "cancelled"


@pytest.mark.db
def test_suppressed_after_approval_is_cancelled_and_the_lead_suppressed(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    db.table("suppression").insert({"domain": "glow0.com", "reason": "pytest"}).execute()
    gm = Gmail()
    assert _go(db, gm, mb)["cancelled"] == 1 and gm.sent == []
    assert touch(db, l["id"])["status"] == "cancelled" and lead(db, l["id"])["status"] == "suppressed"


@pytest.mark.db
def test_touch_1_to_a_company_we_already_emailed_is_cancelled(world):
    db, bid, mb = world
    make_leads(db, bid, mb, 1, status="sent", touch_status="sent", offset=0)
    (b,) = make_leads(db, bid, mb, 1, touch_status="scheduled", offset=1, tkw={"send_at": PAST})
    db.table("leads").update({"domain": "glow0.com", "owner_email": "other@glow0.com"}).eq("id", b["id"]).execute()
    gm = Gmail()
    assert _go(db, gm, mb)["cancelled"] == 1 and gm.sent == [] and touch(db, b["id"])["status"] == "cancelled"


@pytest.mark.db
def test_not_yet_due_or_outside_the_window_is_left_scheduled(world):
    db, bid, mb = world
    (later,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": "2026-11-10T19:00:00+00:00"}, offset=0)
    (night,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST}, offset=1, tz="America/Chicago")
    gm = Gmail()
    saturday = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
    assert send_scheduled(db, lambda a: gm, mb, NOW - timedelta(hours=2), SETTINGS).get("sent", 0) == 0  # 10:00 Chicago: neither is due yet
    assert send_scheduled(db, lambda a: gm, mb, saturday, SETTINGS)["deferred"] == 2 and gm.sent == []
    assert touch(db, later["id"])["status"] == "scheduled" and touch(db, night["id"])["status"] == "scheduled"
    assert send_scheduled(db, lambda a: gm, mb, saturday, SETTINGS, anytime=True)["sent"] == 2


@pytest.mark.db
def test_create_draft_failure_reverts_to_scheduled(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})

    class Down(Gmail):
        def create(self, **kw):
            raise RuntimeError("quota")

    gm = Down()
    out = _go(db, gm, mb)
    assert out["errors"] == 1 and gm.sent == [] and touch(db, l["id"])["status"] == "scheduled"


@pytest.mark.db
def test_send_draft_failure_leaves_sending_and_is_not_retried(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})

    class Lost(Gmail):
        def send(self, **kw):
            raise TimeoutError("ambiguous")

    out = _go(db, Lost(), mb)
    t = touch(db, l["id"])
    assert out["stranded"] == 1 and t["status"] == "sending" and t["gmail_draft_id"] == "draft1"
    gm = Gmail()
    assert _go(db, gm, mb).get("sent", 0) == 0 and gm.created == []


@pytest.mark.db
def test_touch_2_replies_in_the_touch_1_thread(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, status="sent", touch_no=2, touch_status="scheduled", tkw={"send_at": PAST, "gmail_thread_id": "thread-1"})
    gm = Gmail()
    assert _go(db, gm, mb)["sent"] == 1
    msg = gm.created[0]
    assert msg["threadId"] == "thread-1" and b"In-Reply-To: <first@x>" in base64.urlsafe_b64decode(msg["raw"])
    assert touch(db, l["id"], 2)["status"] == "sent" and lead(db, l["id"])["status"] == "sent"


def _tick(db, gm, on=True, **kw):
    import gtm.send as send

    send.setting = lambda key, db=None: on  # the sending_on flag; the real settings row is never touched
    return send_tick(db, lambda addr: gm, lambda s, p: {"kind": "other"}, settings=SETTINGS, now=NOW, **{"thread_messages": lambda svc, tid: [], "recent_bounces": lambda svc: [], **kw})


@pytest.fixture(autouse=True)
def _restore_setting():
    import gtm.send as send

    real = send.setting
    yield
    send.setting = real


@pytest.mark.db
def test_tick_does_nothing_when_sending_off(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    gm = Gmail()
    assert _tick(db, gm, on=False) == {"off": 1} and gm.sent == [] and touch(db, l["id"])["status"] == "scheduled"


@pytest.mark.db
def test_force_sends_even_when_off(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    gm = Gmail()
    out = _tick(db, gm, on=False, force=True)
    assert out["send"]["sent"] == 1 and touch(db, l["id"])["status"] == "sent"
    assert db.table("mailboxes").select("replies_checked_at").eq("id", mb["id"]).execute().data[0]["replies_checked_at"]


@pytest.mark.db
def test_tick_schedules_and_sends_an_approved_touch(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="approved")
    gm = Gmail()
    out = _tick(db, gm, anytime=True)
    assert out["scheduled"] == 1 and out["send"]["sent"] == 1 and touch(db, l["id"])["status"] == "sent"


@pytest.mark.db
def test_tick_does_nothing_when_mailbox_paused(world):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    db.table("mailboxes").update({"paused": True, "paused_reason": "pytest"}).eq("id", mb["id"]).execute()
    gm = Gmail()
    out = _tick(db, gm)
    assert out["scheduled"] == 0 and out["send"] == {} and gm.sent == [] and touch(db, l["id"])["status"] == "scheduled"


@pytest.mark.db
def test_bounce_spike_auto_pauses_and_sends_nothing(world):
    db, bid, mb = world
    old = datetime.combine(TODAY - timedelta(days=2), time(12), tzinfo=timezone.utc).isoformat()
    history = make_leads(db, bid, mb, 25, status="sent", touch_status="sent", offset=100, prefix="PYB_", sent_at=old)
    for l in history[:5]:  # 5 of 25 bounced = 20%
        db.table("leads").update({"status": "bounced"}).eq("id", l["id"]).execute()
    (due,) = make_leads(db, bid, mb, 1, touch_status="scheduled", offset=0, tkw={"send_at": PAST})
    gm = Gmail()
    out = _tick(db, gm)
    row = db.table("mailboxes").select("*").eq("id", mb["id"]).execute().data[0]
    assert out["paused"] == 1 and gm.sent == [] and row["paused"] is True and "bounce" in row["paused_reason"]
    assert touch(db, due["id"])["status"] == "scheduled"


@pytest.mark.db
def test_tick_reads_replies_before_sending(world):
    """Anti-goal: emailing after an opt-out. The lead is still `sent` in the database until replies are read."""
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, status="sent", touch_no=2, touch_status="scheduled", tkw={"send_at": PAST, "gmail_thread_id": "thread-1"})
    db.table("touches").insert({"lead_id": l["id"], "touch_no": 1, "status": "sent", "gmail_thread_id": "thread-1", "sent_at": "2026-11-07T12:00:00+00:00"}).execute()
    gm = Gmail()
    inbox = {"thread-1": [{"from": "Dana <dana@glow0.com>", "subject": "Re: s", "headers": {}, "body": "Please stop emailing me."}]}
    out = _tick(db, gm, thread_messages=lambda svc, tid: inbox.get(tid, []))  # other mailboxes' leads may have threads too
    assert gm.sent == [] and out["replies"] == {"opt_out": 1}
    assert touch(db, l["id"], 2)["status"] == "cancelled" and lead(db, l["id"])["status"] == "unsubscribed"


def _checked(db, mb, ago_min):
    db.table("mailboxes").update({"replies_checked_at": (NOW - timedelta(minutes=ago_min)).isoformat()}).eq("id", mb["id"]).execute()


@pytest.mark.db
@pytest.mark.parametrize("ago,reads", [(1, False), (11, True), (None, True)])
def test_replies_are_read_at_most_every_ten_minutes_but_sending_happens_every_tick(world, ago, reads):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    (h,) = make_leads(db, bid, mb, 1, status="sent", touch_status="sent", offset=50, prefix="REHEARSAL_F_", sent_at="2026-11-07T12:00:00+00:00", tkw={"gmail_thread_id": "t-h"})
    if ago is not None:
        _checked(db, mb, ago)
    seen = []
    out = _tick(db, Gmail(), thread_messages=lambda svc, tid: seen.append(tid) or [])
    assert ("t-h" in seen) is reads and out["send"]["sent"] == 1


@pytest.mark.db
def test_force_reads_replies_even_when_recently_checked(world):
    db, bid, mb = world
    make_leads(db, bid, mb, 1, status="sent", touch_status="sent", prefix="REHEARSAL_F_", sent_at="2026-11-07T12:00:00+00:00", tkw={"gmail_thread_id": "t-f"})
    _checked(db, mb, 1)
    seen = []
    _tick(db, Gmail(), force=True, thread_messages=lambda svc, tid: seen.append(tid) or [])
    assert "t-f" in seen


@pytest.mark.db
@pytest.mark.parametrize("broken", ["service", "replies"])
def test_a_gmail_failure_pauses_that_mailbox_with_the_reason(world, broken):
    db, bid, mb = world
    (l,) = make_leads(db, bid, mb, 1, touch_status="scheduled", tkw={"send_at": PAST})
    make_leads(db, bid, mb, 1, status="sent", touch_status="sent", offset=60, prefix="REHEARSAL_F_", sent_at="2026-11-07T12:00:00+00:00", tkw={"gmail_thread_id": "t-g"})
    gm = Gmail()

    def gmail_for(addr):
        if broken == "service":
            raise RuntimeError("Gmail token missing or invalid for " + addr + ": re-authorise on the Mac")
        return gm

    def tm(svc, tid):
        raise ConnectionError("x" * 300)

    import gtm.send as send

    send.setting = lambda key, db=None: True
    out = send_tick(db, gmail_for, lambda s, p: {"kind": "other"}, settings=SETTINGS, now=NOW, thread_messages=tm, recent_bounces=lambda svc: [])
    row = db.table("mailboxes").select("*").eq("id", mb["id"]).execute().data[0]
    assert out["paused"] == 1 and gm.sent == [] and row["paused"] is True
    want = "gmail: RuntimeError: Gmail token missing" if broken == "service" else "gmail: ConnectionError: " + "x" * 120
    assert row["paused_reason"].startswith(want) and len(row["paused_reason"]) <= len("gmail: ConnectionError: ") + 120
    assert touch(db, l["id"])["status"] == "scheduled"


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

    created: list = []

    def create(self, **kw):
        self.created = [*self.created, kw["body"]["message"]]
        return type("E", (), {"execute": lambda s: {"id": f"draft{len(self.created)}"}})()

    def threads(self):
        return self

    def get(self, **kw):
        return type("E", (), {"execute": lambda s: {"messages": [{"payload": {"headers": [{"name": "Message-ID", "value": "<first@x>"}]}}]}})()


@pytest.fixture
def world():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    mb = db.table("mailboxes").insert({"address": "pytest-send@example.com", "daily_cap": 40, "enabled_on": TODAY.isoformat()}).execute().data[0]
    yield db, bid, mb
    db.table("suppression").delete().like("reason", "pytest%").execute()
    purge_test_suppression(db)  # written by apply_reply in the reply-check test; only the tests' own addresses
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("leads").delete().like("place_id", "PYB_%").execute()
    db.table("leads").delete().like("place_id", "REHEARSAL_B_%").execute()
    db.table("leads").delete().like("place_id", "REHEARSAL_F_%").execute()
    db.table("mailboxes").delete().like("address", "pytest-send%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def make_leads(db, bid, mb, n, status="drafted", touch_no=1, touch_status="drafted", offset=0, prefix="TEST_", sent_at=None, tkw=None, **lead_kw):
    items = [{"placeId": f"{prefix}{offset + i:03d}", "title": f"Spa {i}", "website": f"https://glow{offset + i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(n)]
    rows = [{**place_to_lead(it, bid), "status": status, "owner_name": "Dana W", "owner_email": f"dana@glow{offset + i}.com", "email_verified": True,
             "mailbox_id": mb["id"], **lead_kw} for i, it in enumerate(items)]
    leads = db.table("leads").insert(rows).execute().data
    db.table("touches").insert([{"lead_id": l["id"], "touch_no": touch_no, "status": touch_status, "gmail_draft_id": f"d{l['place_id']}", "subject": "s", "body": "b",
                                 "scheduled_for": TODAY.isoformat(), "sent_at": sent_at, **(tkw or {})} for l in leads]).execute()
    return leads


def touch(db, lead_id, n=1):
    return db.table("touches").select("*").eq("lead_id", lead_id).eq("touch_no", n).execute().data[0]


def lead(db, lead_id):
    return db.table("leads").select("*").eq("id", lead_id).execute().data[0]