import pytest

from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead
from gtm.select import run_select, select_decision

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
