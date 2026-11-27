from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from gtm import settings_store
from gtm.db import fetch_all, get_db
from gtm.scrape import new_batch, place_to_lead
from gtm.select import _blocklists, run_select, select_decision

HANDOFF = {"text": "Booking is by phone or Instagram DM", "url": "https://glow.com/book", "quote": "call us"}
SIGNAL = {"text": "Hiring a front desk coordinator", "url": "https://glow.com/careers", "date": "2026-10-28", "quote": "hiring"}


def lead(**kw):
    base = {"status": "signalled", "owner_email": "dana@glow.com", "email_verified": True, "domain": "glow.com", "vector": "capacity",
            "signal_led": True, "signal": {"current_signal": SIGNAL, "relevant_handoff": HANDOFF}}
    return {**base, **kw}


def decide(l, suppressed=(), contacted=()):
    return select_decision(l, set(suppressed), set(contacted))


def test_signal_led_lead_is_selected():
    assert decide(lead()) == (True, "signal-led")


def test_relevance_led_lead_with_an_observed_handoff_is_selected():
    assert decide(lead(signal_led=False, signal={"current_signal": None, "relevant_handoff": HANDOFF})) == (True, "relevance-led")


def test_no_vector_means_no_observed_handoff_and_is_not_selected():
    assert decide(lead(vector=None, signal_led=False, signal={"current_signal": None, "relevant_handoff": None})) == (False, "no_handoff")


@pytest.mark.parametrize("kw", [{"owner_email": None}, {"email_verified": False}, {"email_verified": None}])
def test_missing_or_unverified_email_is_not_selected(kw):
    assert decide(lead(**kw)) == (False, "no_email")


def test_lead_that_is_not_signalled_yet_is_not_selected():
    assert decide(lead(status="enriched")) == (False, "not_signalled")


def test_suppressed_email_blocks():
    assert decide(lead(), suppressed={"dana@glow.com"}) == (False, "suppressed")


def test_suppressed_domain_blocks_every_address_on_it():
    assert decide(lead(owner_email="anyone@glow.com"), suppressed={"glow.com"}) == (False, "suppressed")


def test_suppression_match_ignores_case():
    assert decide(lead(owner_email="Dana@Glow.com"), suppressed={"dana@glow.com"}) == (False, "suppressed")


def test_already_contacted_email_or_company_domain_is_not_selected():
    assert decide(lead(), contacted={"dana@glow.com"}) == (False, "already_contacted")
    assert decide(lead(owner_email="other@glow.com"), contacted={"glow.com"}) == (False, "already_contacted")  # one Touch 1 per company


def test_suppressed_wins_over_every_other_reason():
    assert decide(lead(vector=None), suppressed={"glow.com"}, contacted={"glow.com"}) == (False, "suppressed")


@pytest.fixture
def signalled():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    items = [{"placeId": f"TEST_{i}", "title": f"Spa {i}", "website": f"https://glow{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(4)]
    rows = [{**place_to_lead(i, bid), "status": "signalled", "owner_name": "Dana W", "owner_title": "Owner", "owner_email": f"dana@glow{n}.com",
             "email_verified": True, "vector": "capacity", "signal_led": n == 0, "signal": {"current_signal": SIGNAL if n == 0 else None, "relevant_handoff": HANDOFF}}
            for n, i in enumerate(items)]
    db.table("leads").insert(rows).execute()
    yield db, bid
    db.table("suppression").delete().like("reason", "pytest%").execute()
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def row(db, i):
    return db.table("leads").select("*").eq("place_id", f"TEST_{i}").execute().data[0]


@pytest.mark.db
def test_run_select_marks_selected_suppressed_and_leaves_others_with_a_reason(signalled):
    db, bid = signalled
    db.table("suppression").insert({"domain": "glow1.com", "reason": "pytest"}).execute()
    other = db.table("leads").select("id").eq("place_id", "TEST_2").execute().data[0]["id"]
    db.table("touches").insert({"lead_id": other, "touch_no": 1, "status": "sent"}).execute()  # glow2.com already contacted
    assert run_select(db, lambda s, p: {"reason": "Hiring a coordinator while booking stays on phone and DM."}, bid) == 2
    a, b, c, d = (row(db, i) for i in range(4))
    assert (a["status"], a["select_reason"]) == ("selected", "Hiring a coordinator while booking stays on phone and DM.")
    assert (b["status"], b["reject_reason"]) == ("suppressed", "suppressed")
    assert (c["status"], c["reject_reason"]) == ("signalled", "already_contacted")
    assert d["status"] == "selected"
    assert run_select(db, lambda s, p: pytest.fail("rejected leads never reach the model"), bid) == 0  # selected ones are no longer `signalled`


@pytest.mark.db
def test_reason_falls_back_to_the_observed_evidence_when_the_model_fails(signalled):
    db, bid = signalled

    def boom(s, p):
        raise RuntimeError("down")

    run_select(db, boom, bid)
    r = row(db, 0)
    assert r["status"] == "selected" and "Hiring a front desk coordinator" in r["select_reason"]


@pytest.mark.db
def test_lead_without_a_handoff_stays_signalled_with_the_reason_stored(signalled):
    db, bid = signalled
    db.table("leads").update({"signal": {"current_signal": None, "relevant_handoff": None}}).eq("place_id", "TEST_3").execute()
    run_select(db, lambda s, p: {"reason": "ok"}, bid)
    d = row(db, 3)
    assert (d["status"], d["reject_reason"]) == ("signalled", "no_handoff")


# ---- _blocklists: recontact release behind the recontact_on flag (Plan 9, Task 3). Fake db: no network, no real rows. ----
TODAY = date(2027, 2, 1)


def ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


class _Q:
    """Supabase-style chained query over a list of dicts: select/eq/in_/order/range/execute. Projects the selected columns and,
    like the Data API, returns at most 1000 rows when no range is asked for."""

    def __init__(self, db, name, rows):
        self.db, self.name, self.rows, self.cols, self.filters, self.span = db, name, rows, "*", [], (0, 999)

    def select(self, cols="*"):
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def order(self, col):
        return self

    def range(self, lo, hi):
        self.span = (lo, hi)
        return self

    def execute(self):
        self.db.selects.append((self.name, self.cols))
        rows = [r for r in self.rows if all(f(r) for f in self.filters)][self.span[0] : self.span[1] + 1]
        cols = None if self.cols == "*" else self.cols.split(",")
        return SimpleNamespace(data=[{c: r.get(c) for c in cols} if cols else dict(r) for r in rows])


class _DB:
    def __init__(self, tables, boom=()):
        self.tables, self.boom, self.selects = tables, set(boom), []

    def table(self, name):
        if name in self.boom:
            raise RuntimeError(f"{name} unavailable")
        return _Q(self, name, self.tables.get(name, []))

    def queried(self):
        return {n for n, _ in self.selects}


def world(on=True, sup=(), hist=(), leads=(), touches=(), settings=(), boom=()):
    flag = [] if on is None else [{"key": "recontact_on", "value": on}]
    numbered = lambda rows: [{"id": i, **r} for i, r in enumerate(rows, 1)]
    return _DB({"settings": flag + [{"key": k, "value": v} for k, v in settings], "suppression": numbered(sup), "contact_history": numbered(hist),
                "leads": list(leads), "touches": numbered(touches)}, boom)


def blocklists(db, today=TODAY):
    """setting() caches for 60 s: clear around every call so a fake flag never leaks into another test."""
    settings_store.clear_cache()
    try:
        return _blocklists(db, today)
    finally:
        settings_store.clear_cache()


def legacy(db):
    """The function as it was before Plan 9, copied verbatim."""
    sup = set()
    for r in fetch_all(lambda: db.table("suppression").select("email,domain").order("id")):
        sup |= {v.lower() for v in (r["email"], r["domain"]) if v}
    sent = [t["lead_id"] for t in fetch_all(lambda: db.table("touches").select("lead_id").eq("status", "sent").order("id"))]
    contacted = set()
    for i in range(0, len(sent), 100):
        for r in db.table("leads").select("owner_email,domain").in_("id", sent[i : i + 100]).execute().data:
            contacted |= {v.lower() for v in (r["owner_email"], r["domain"]) if v}
    return sup, contacted


def sup_row(email=None, domain=None, reason="notion-contacted"):
    return {"email": email, "domain": domain, "reason": reason}


def hist_row(email, domain, outcome="no_reply", last=100, **kw):
    return {"email": email, "domain": domain, "outcome": outcome, "last_sent_on": ago(last) if isinstance(last, int) else last, "round": 1, **kw}


def os_lead(i, status="sent", sent=(100,), place_id=None, rnd=1, **kw):
    """One OS lead with its sent touches (days ago). Returns (lead, touches)."""
    lead = {"id": f"L{i}", "owner_email": f"o{i}@d{i}.com", "domain": f"d{i}.com", "status": status, "place_id": place_id or f"ChIJ{i}", "round": rnd, **kw}
    return lead, [{"lead_id": f"L{i}", "status": "sent", "sent_at": ago(n) + "T14:00:00+00:00"} for n in sent]


def keys_of(lead):
    return {lead["owner_email"], lead["domain"]}


def stack(*pairs):
    return [l for l, _ in pairs], [t for _, ts in pairs for t in ts]


def test_blocklists_with_recontact_off_equals_the_old_function_and_never_reads_the_ledger():
    sup = [sup_row("A@Spa.com"), sup_row(domain="Glow.com", reason="sheet-sent"), sup_row("x@y.com", "y.com", "bounce"), sup_row("", "", "unsubscribe")]
    pairs = [os_lead(i, sent=(100, 90) if i % 3 == 0 else (40,), owner_email=None if i == 7 else f"O{i}@D{i % 40}.com", domain=f"D{i % 40}.com") for i in range(250)]
    leads, touches = stack(*pairs)
    touches += [{"lead_id": "L1", "status": "cancelled", "sent_at": None}, {"lead_id": "L260", "status": "approved", "sent_at": None}]
    for flag in (False, None):  # stored off, and no stored row at all
        db = world(on=flag, sup=sup, leads=leads, touches=touches, boom=("contact_history",))  # the ledger table raises when touched
        got = blocklists(db)
        assert got == legacy(db)
        assert got[0] >= {"a@spa.com", "glow.com", "y.com"} and len(got[1]) > 50
        assert db.queried() == {"settings", "suppression", "touches", "leads"}
        assert {c for n, c in db.selects if n == "leads"} == {"owner_email,domain"}  # no new column read while off


@pytest.mark.parametrize("boom", [("settings",), ("settings", "contact_history")])
def test_blocklists_flag_read_error_means_off(boom):
    sup = [sup_row("a@glow.com", "glow.com")]
    leads, touches = stack(os_lead(1, sent=(300,)))
    db = world(sup=sup, hist=[hist_row("a@glow.com", "glow.com")], leads=leads, touches=touches, boom=boom)  # old sent lead, clear ledger: would lift if on
    assert blocklists(db) == legacy(db) == ({"a@glow.com", "glow.com"}, keys_of(leads[0]))


def test_blocklists_on_lifts_a_suppression_key_only_with_a_clear_ledger_row():
    sup = [sup_row("a@glow.com"), sup_row(domain="glow.com"), sup_row("g@auto.com", "auto.com", "sheet-sent"), sup_row("b@young.com", "young.com"),
           sup_row("c@none.com"), sup_row("d@replied.com", "replied.com"), sup_row("e@capped.com", "capped.com"), sup_row("f@unk.com", "unk.com"),
           sup_row("h@nodate.com", "nodate.com")]
    hist = [hist_row("a@glow.com", "glow.com"), hist_row("g@auto.com", "auto.com", "auto_reply", 61), hist_row("b@young.com", "young.com", last=59),
            hist_row("d@replied.com", "replied.com", "replied", 200), hist_row("e@capped.com", "capped.com", last=200, round=3),
            hist_row("f@unk.com", "unk.com", "unknown", 200), hist_row("h@nodate.com", "nodate.com", last=None)]
    suppressed, _ = blocklists(world(sup=sup, hist=hist))
    every = {k for r in sup for k in (r["email"], r["domain"]) if k}
    assert suppressed == every - {"a@glow.com", "glow.com", "g@auto.com", "auto.com"}


def test_blocklists_on_keeps_every_permanent_reason():
    reasons = ["unsubscribe", "not-interested", "bounce", "sheet-dropped", "some-future-reason", None, ""]
    sup = [sup_row(f"p{i}@x{i}.com", f"x{i}.com", r) for i, r in enumerate(reasons)]
    hist = [hist_row(f"p{i}@x{i}.com", f"x{i}.com") for i in range(len(reasons))]  # every one has an old clear ledger row
    suppressed, _ = blocklists(world(sup=sup, hist=hist))
    assert suppressed == {k for r in sup for k in (r["email"], r["domain"])}


def test_blocklists_on_a_bounced_email_keeps_its_cooldown_domain_blocked_too():
    sup = [sup_row("dana@glow.com", reason="bounce"), sup_row(domain="glow.com", reason="notion-contacted")]
    suppressed, _ = blocklists(world(sup=sup, hist=[hist_row("dana@glow.com", "glow.com")]))
    assert suppressed == {"dana@glow.com", "glow.com"}


def test_blocklists_on_keeps_a_ledger_row_beyond_the_1000_row_api_cap_in_force():
    hist = [hist_row("z@late.com", "late.com")] + [hist_row(f"k{i}@f{i}.com", f"f{i}.com") for i in range(1050)] + [hist_row("z@late.com", "late.com", "replied", 200, round=2)]
    suppressed, _ = blocklists(world(sup=[sup_row("z@late.com", "late.com")], hist=hist))  # the clear row is on page one, the replied row on page two
    assert suppressed == {"z@late.com", "late.com"}


@pytest.mark.parametrize("status", ["replied", "bounced", "unsubscribed", "suppressed", "booked"])
def test_blocklists_on_keeps_a_replied_lead_contacted_forever(status):
    leads, touches = stack(os_lead(1, status=status, sent=(200,)))  # any status but sent: the lead was answered, bounced or opted out
    assert blocklists(world(leads=leads, touches=touches))[1] == keys_of(leads[0])


def test_blocklists_on_lifts_an_old_sent_lead_with_no_reply():
    undated = os_lead(6)
    undated[1][0]["sent_at"] = None
    leads, touches = stack(os_lead(1), os_lead(2, sent=(30,)), os_lead(3), os_lead(4, place_id="TEST_4"), os_lead(5, rnd=3), undated, os_lead(7, sent=(100, 10)))
    touches.append({"lead_id": "L3", "status": "approved", "sent_at": None})  # a touch that may still go out
    _, contacted = blocklists(world(leads=leads, touches=touches))
    assert contacted == set().union(*(keys_of(l) for l in leads[1:]))  # everything but the old no-reply lead
    assert keys_of(leads[0]).isdisjoint(contacted)


def test_blocklists_on_with_an_empty_ledger_changes_only_what_lead_released_frees():
    sup = [sup_row("a@glow.com", "Glow.com"), sup_row("x@y.com", reason="unsubscribe")]
    leads, touches = stack(os_lead(1), os_lead(2, sent=(10,)))
    db = world(sup=sup, leads=leads, touches=touches)
    suppressed, contacted = blocklists(db)
    old_sup, old_contacted = legacy(db)
    assert suppressed == old_sup
    assert contacted == old_contacted - keys_of(leads[0])


@pytest.mark.parametrize("name, value, lifted", [("recontact_days", 30, True), ("recontact_days", 0, False), ("recontact_max_rounds", 1, False)])
def test_blocklists_on_reads_the_days_and_rounds_settings(name, value, lifted):  # a stored 0 falls back to the default: 40 days old stays blocked
    sup, hist = [sup_row("a@glow.com", "glow.com")], [hist_row("a@glow.com", "glow.com", last=40)]
    suppressed, _ = blocklists(world(sup=sup, hist=hist, settings=[(name, value)]))
    assert suppressed == (set() if lifted else {"a@glow.com", "glow.com"})


def test_blocklists_on_today_defaults_to_the_current_date():
    sup, hist = [sup_row("a@glow.com")], [hist_row("a@glow.com", None, last=(date.today() - timedelta(days=100)).isoformat())]
    settings_store.clear_cache()
    try:
        assert _blocklists(world(sup=sup, hist=hist)) == (set(), set())
    finally:
        settings_store.clear_cache()


def test_blocklists_on_ledger_read_error_raises():
    leads, touches = stack(os_lead(1))
    db = world(sup=[sup_row("a@glow.com")], leads=leads, touches=touches, boom=("contact_history",))
    with pytest.raises(RuntimeError, match="contact_history"):
        blocklists(db)
    assert "leads" not in db.queried()  # the ledger is read before anything that needs the new leads.round column


@pytest.mark.parametrize("table", ["suppression", "touches", "leads"])
def test_blocklists_on_any_other_read_error_raises_too(table):
    leads, touches = stack(os_lead(1))
    with pytest.raises(RuntimeError, match=table):
        blocklists(world(sup=[sup_row("a@glow.com")], leads=leads, touches=touches, boom=(table,)))
