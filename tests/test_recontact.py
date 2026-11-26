"""Pure tests for gtm/recontact.py: no database, no network, no environment."""
import ast
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

from gtm import recontact
from gtm.recontact import (CLEAR_OUTCOMES, COOLDOWN_REASONS, OPEN_TOUCH_STATUSES, OUTCOMES, clear_rows, keys, last_sent_bound,
                           lead_released, notion_outcome, released_keys)
from gtm.status import Status

TODAY = date(2027, 2, 1)


def ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def sup(email=None, domain=None, reason="notion-contacted"):
    return {"email": email, "domain": domain, "reason": reason}


def hist(email="dana@glow.com", domain="glow.com", outcome="no_reply", last=None, **kw):
    return {"email": email, "domain": domain, "outcome": outcome, "last_sent_on": last or ago(100), **kw}


def rel(sup_rows, hist_rows, days=60, max_rounds=3):
    return released_keys(sup_rows, hist_rows, TODAY, days, max_rounds)


def test_module_is_pure_no_db_config_or_network_imports():
    tree = ast.parse(Path(recontact.__file__).read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert mods <= {"__future__", "datetime", "gtm.status"}


def test_constants_match_the_policy():
    assert COOLDOWN_REASONS == {"notion-contacted", "sheet-sent"}
    assert CLEAR_OUTCOMES == {"no_reply", "auto_reply"}
    assert set(OUTCOMES) == {"no_reply", "auto_reply", "replied", "bounce", "negative", "opt_out", "do_not_contact", "disqualified", "booked", "client", "unknown"}
    assert OPEN_TOUCH_STATUSES == {"drafted", "held", "edited", "approved", "scheduled", "sending"}


def test_keys_lowercase_and_drop_empty():
    assert keys(" Dana@Glow.COM ", "Glow.com ") == {"dana@glow.com", "glow.com"}
    assert keys(None, "") == set()
    assert keys("  ", None) == set()
    assert keys("a@b.com", None) == {"a@b.com"}  # the domain is never derived from the email


@pytest.mark.parametrize("last", [ago(100), TODAY - timedelta(days=100), ago(100) + "T12:30:00+00:00"])
def test_released_keys_lifts_a_clear_old_cooldown_contact(last):
    s = [sup(email="dana@glow.com"), sup(domain="glow.com", reason="sheet-sent")]
    assert rel(s, [hist(last=last)]) == {"dana@glow.com", "glow.com"}


@pytest.mark.parametrize("outcome", sorted(CLEAR_OUTCOMES))
def test_both_clear_outcomes_release_and_a_missing_round_means_one(outcome):
    assert rel([sup(email="dana@glow.com")], [hist(outcome=outcome)]) == {"dana@glow.com", "glow.com"}
    assert rel([], [hist(outcome=outcome, round=2)]) == {"dana@glow.com", "glow.com"}
    assert rel([], [hist(outcome=outcome, round=None)]) == {"dana@glow.com", "glow.com"}


def test_released_keys_needs_a_ledger_row():
    s = [sup(email="dana@glow.com"), sup(domain="glow.com")]
    assert rel(s, []) == set()
    assert rel(s, [hist(email="other@x.com", domain="x.com")]) == {"other@x.com", "x.com"}  # an unrelated row frees only its own keys


@pytest.mark.parametrize("reason", ["do-not-contact", "notion-bounce", "bounce", "not-interested", "opt-out reply", "sheet-dropped", "something-new", None, ""])
def test_released_keys_never_lifts_a_permanent_reason(reason):
    assert rel([sup(email="dana@glow.com", domain="glow.com", reason=reason)], [hist()]) == set()
    assert rel([sup(email="dana@glow.com", reason=reason)], [hist()]) == set()
    assert rel([sup(domain="glow.com", reason=reason)], [hist()]) == set()


def test_a_permanent_row_on_any_shared_key_blocks_the_whole_contact():
    s = [sup(email="dana@glow.com", reason="notion-bounce"), sup(domain="glow.com", reason="notion-contacted")]
    assert rel(s, [hist()]) == set()  # neither the bounced email nor the cooldown domain comes back


@pytest.mark.parametrize("days,age,out", [(90, 90, True), (90, 89, False), (90, 91, True), (60, 60, True), (60, 59, False)])
def test_released_keys_boundary_day_90_in_day_89_out(days, age, out):
    got = rel([sup(email="dana@glow.com")], [hist(last=ago(age))], days=days)
    assert got == ({"dana@glow.com", "glow.com"} if out else set())


@pytest.mark.parametrize("days", [0, -5])
def test_a_window_below_one_day_lifts_nothing(days):
    assert rel([], [hist(last=ago(0))], days=days) == set()


@pytest.mark.parametrize("kw", [
    {"outcome": "unknown"}, {"outcome": "replied"}, {"outcome": "bounce"}, {"outcome": "negative"}, {"outcome": "opt_out"},
    {"outcome": "do_not_contact"}, {"outcome": "disqualified"}, {"outcome": "booked"}, {"outcome": "client"},
    {"outcome": None}, {"outcome": ""}, {"outcome": "No_Reply"}, {"outcome": "garbage"}, {"outcome": ["no_reply"]},
    {"last": ago(10)}, {"last": ago(59)}, {"last": ago(-3)}, {"last": "not-a-date"}, {"last": ""}, {"last": 20261001},
    {"round": 3}, {"round": 4}, {"round": "x"},
])
def test_released_keys_unclear_outcome_recent_date_or_round_at_cap_blocks(kw):
    row = hist(**{k: v for k, v in kw.items() if k != "last"})
    if "last" in kw:
        row["last_sent_on"] = kw["last"]
    assert rel([sup(email="dana@glow.com")], [row]) == set()


def test_a_ledger_row_without_a_date_blocks():
    row = hist()
    del row["last_sent_on"]
    assert rel([], [row]) == set()
    assert rel([], [{**row, "last_sent_on": None}]) == set()


def test_one_unclear_ledger_row_taints_a_shared_domain():
    clear = hist(email="a@glow.com")
    for bad in (hist(email="b@glow.com", outcome="replied"), hist(email="b@glow.com", last=ago(5)), hist(email="b@glow.com", round=3)):
        got = rel([], [clear, bad])
        assert "glow.com" not in got  # the shared domain stays blocked
        assert got == {"a@glow.com"}  # the contact's own address is still its own


def test_clear_rows_drops_a_row_sharing_a_domain_with_an_unclear_row():
    a, b, c = hist(email="a@glow.com"), hist(email="b@glow.com", outcome="replied"), hist(email="c@other.com", domain="other.com")
    assert clear_rows([], [a, b, c], TODAY, 60, 3) == [c]


def test_clear_rows_keeps_input_order_and_the_same_rows():
    rows = [hist(email=f"{n}@{n}.com", domain=f"{n}.com", last=ago(70 + i)) for i, n in enumerate(["zed", "amy", "kim"])]
    out = clear_rows([], rows, TODAY, 60, 3)
    assert out == rows and all(o is r for o, r in zip(out, rows))


def test_clear_rows_drops_permanent_unclear_recent_and_keyless_rows():
    rows = [hist(email="a@a.com", domain="a.com"), hist(email="b@b.com", domain="b.com"), hist(email="c@c.com", domain="c.com", last=ago(3)),
            hist(email=None, domain=None), hist(email="d@d.com", domain="d.com", round=3), hist(email="e@e.com", domain="e.com")]
    s = [sup(domain="a.com", reason="do-not-contact"), sup(email="b@b.com", reason="notion-contacted")]
    assert clear_rows(s, rows, TODAY, 60, 3) == [rows[1], rows[5]]


def test_released_keys_is_always_a_subset_of_cooldown_keys_and_misses_permanent_keys():
    rnd = random.Random(20261126)
    people = [(f"p{i}@d{i // 2}.com", f"d{i // 2}.com") for i in range(8)]  # pairs of people share a company domain
    reasons = sorted(COOLDOWN_REASONS) * 3 + ["do-not-contact", "notion-bounce", "sheet-dropped", "mystery", None]
    outcomes = ["no_reply"] * 6 + ["auto_reply"] * 2 + list(OUTCOMES) + [None]
    days, cap, nonempty = 60, 3, 0

    def pick():  # a person's email and domain, or just one of the two
        email, domain = rnd.choice(people)
        return rnd.choice([(email, domain)] * 4 + [(email, None), (None, domain)])

    def clear(r):  # independent oracle for "clear", written differently from the module
        try:
            age = (TODAY - date.fromisoformat(r["last_sent_on"])).days
        except (TypeError, ValueError):
            return False
        return r["outcome"] in ("no_reply", "auto_reply") and age >= days and (r.get("round") or 1) < cap

    def keyset(r):
        return {v.lower() for v in (r["email"], r["domain"]) if v}

    for _ in range(200):
        s = [sup(*pick(), rnd.choice(reasons)) for _ in range(rnd.randint(0, 4))]
        h = [hist(*pick(), rnd.choice(outcomes), last=rnd.choice([ago(rnd.randint(0, 150))] * 6 + [None, "junk"]), round=rnd.choice([None, 1, 2, 3, 4]))
             for _ in range(rnd.randint(0, 5))]
        got = released_keys(s, h, TODAY, days, cap)
        clear_keys = set().union(*(keyset(r) for r in h if clear(r)))
        unclear_keys = set().union(*(keyset(r) for r in h if not clear(r)))
        permanent = set().union(*(keyset(r) for r in s if r["reason"] not in COOLDOWN_REASONS))
        assert got <= clear_keys
        assert not got & permanent
        assert not got & unclear_keys
        nonempty += bool(got)
        out = clear_rows(s, h, TODAY, days, cap)
        assert all(clear(r) and keyset(r) <= got and not keyset(r) & permanent for r in out)
    assert nonempty > 50  # the generator really exercises the release path


def _lead(**kw):
    return {"status": "sent", "place_id": "ChIJrealplace", "round": 1, **kw}


def _sent(*ages):
    return [{"status": "sent", "touch_no": i + 1, "sent_at": f"{ago(a)}T15:04:05.123456+00:00"} for i, a in enumerate(ages)]


def test_lead_released_positive_controls():
    assert lead_released(_lead(), _sent(67, 64, 60), TODAY, 60, 3)  # Touch 3 sent exactly 60 days ago
    assert lead_released(_lead(), _sent(97, 94, 90), TODAY, 90, 3)
    assert lead_released(_lead(round=2), _sent(67, 64, 60), TODAY, 60, 3)
    lead = _lead()
    del lead["round"]
    assert lead_released(lead, _sent(67, 64, 60), TODAY, 60, 3)  # missing round means 1
    assert lead_released(_lead(), _sent(67, 64, 60) + [{"status": "cancelled", "sent_at": None}], TODAY, 60, 3)  # a cancelled touch is closed


@pytest.mark.parametrize("status", [s.value for s in Status if s is not Status.SENT])
def test_a_lead_that_is_not_sent_is_never_released(status):
    assert not lead_released(_lead(status=status), _sent(67, 64, 60), TODAY, 60, 3)


@pytest.mark.parametrize("open_status", sorted(OPEN_TOUCH_STATUSES))
def test_a_lead_with_an_open_touch_is_never_released(open_status):
    assert not lead_released(_lead(), _sent(67, 64) + [{"status": open_status, "sent_at": None}], TODAY, 60, 3)


@pytest.mark.parametrize("lead_kw,touches,days", [
    ({}, _sent(67, 64, 59), 60),  # newest sent touch is 59 days old
    ({}, _sent(97, 94, 89), 90),  # 89 days with a 90 day window
    ({}, _sent(100, 97, 5), 60),  # the newest sent touch counts, not the first
    ({}, [], 60),  # nothing was ever sent
    ({}, [{"status": "cancelled", "sent_at": None}], 60),
    ({}, [{"status": "sent"}], 60),  # a sent touch with no timestamp cannot prove age
    ({}, [{"status": "sent", "sent_at": "garbage"}] + _sent(90), 60),
    ({}, _sent(67, 64, 60), 0),  # a window below one day lifts nothing
    ({"round": 3}, _sent(67, 64, 60), 60),  # at the cap
    ({"round": 4}, _sent(67, 64, 60), 60),
    ({"round": "x"}, _sent(67, 64, 60), 60),
    ({"place_id": "TEST_abc"}, _sent(67, 64, 60), 60),
    ({"place_id": "REHEARSAL_abc"}, _sent(67, 64, 60), 60),
    ({"place_id": None}, _sent(67, 64, 60), 60),
    ({"place_id": ""}, _sent(67, 64, 60), 60),
])
def test_lead_released_only_when_sent_old_enough_and_closed(lead_kw, touches, days):
    assert not lead_released(_lead(**lead_kw), touches, TODAY, days, 3)


@pytest.mark.parametrize("status,reply,dnc,want", [
    ("Sent", "", True, "do_not_contact"), ("Bounced", "Bounce", True, "do_not_contact"), ("Client", "Positive", True, "do_not_contact"),
    ("Cadence Complete", "Out of Office", True, "do_not_contact"),
    ("Sent", "Bounce", False, "bounce"), ("Bounced", "", False, "bounce"), ("Not Interested", "Bounce", False, "bounce"), ("Bounced", "Out of Office", False, "bounce"),
    ("Sent", "Negative", False, "negative"), ("Not Interested", "", False, "negative"), ("Disqualified", "Negative", False, "negative"),
    ("Call Booked", "Negative", False, "negative"),
    ("Disqualified", "", False, "disqualified"), ("Disqualified", "Positive", False, "disqualified"), ("Disqualified", "Out of Office", False, "disqualified"),
    ("Call Booked", "", False, "booked"), ("Call Booked", "Positive", False, "booked"),
    ("Client", "", False, "client"), ("Client", "Neutral", False, "client"),
    ("Sent", "Positive", False, "replied"), ("Sent", "Neutral", False, "replied"), ("Cadence Complete", "Something new", False, "replied"),
    ("Replied", "", False, "replied"), ("Replied", "Positive", False, "replied"),
    ("Replied", "Out of Office", False, "replied"),  # pinned: the stricter reading wins when Status says Replied
    ("Sent", "Out of Office", False, "auto_reply"), ("Cadence Complete", "Out of Office", False, "auto_reply"),
    ("Sent", "", False, "no_reply"), ("Follow-up Due", "", False, "no_reply"), ("Cadence Complete", "", False, "no_reply"),
    ("Sent at Touch 2", "", False, "no_reply"),
    ("Ready to Send", "", False, "unknown"), ("", "", False, "unknown"), ("Something odd", "", False, "unknown"), ("Draft", "  ", False, "unknown"),
    ("  CADENCE   complete ", " ", False, "no_reply"), ("sent", "OUT  OF office", False, "auto_reply"), (" bounced ", "", False, "bounce"),
])
def test_notion_outcome_precedence(status, reply, dnc, want):
    assert notion_outcome(status, reply, dnc) == want
    assert want in OUTCOMES


def test_notion_outcome_none_inputs_fail_closed():
    assert notion_outcome(None, None, False) == "unknown"


def test_last_sent_bound_is_the_later_of_last_contacted_and_day_seven():
    initial = date(2026, 9, 2)
    assert last_sent_bound(initial, date(2026, 9, 11)) == date(2026, 9, 11)  # logged later than Day 7
    assert last_sent_bound(initial, date(2026, 9, 5)) == date(2026, 9, 9)  # logged before Day 7: the follow-ups may be unlogged
    assert last_sent_bound(initial, date(2026, 9, 9)) == date(2026, 9, 9)
    assert last_sent_bound(initial, None) == date(2026, 9, 9)
    assert last_sent_bound(initial, date(2026, 8, 1)) == date(2026, 9, 9)
