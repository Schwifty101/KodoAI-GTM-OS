from datetime import date
from pathlib import Path

import pytest

from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead
from gtm.signals import MAX_PAGE_CHARS, SYSTEM, VECTORS, detect_platform, fetch_evidence, judge_to_signal, run_signals, validate_signal

TODAY = date(2026, 11, 10)
PAGES = [
    {"url": "https://glow.com/careers", "text": "We are hiring a Front Desk Coordinator. Posted October 28, 2026. Apply by phone."},
    {"url": "https://glow.com/book", "text": "To book a treatment, call us or send a DM on Instagram. Online booking is not available."},
]


def raw(**kw):
    base = {
        "current_signal": {"text": "Hiring a front desk coordinator", "url": PAGES[0]["url"], "date": "2026-10-28", "quote": "We are hiring a Front Desk Coordinator"},
        "relevant_handoff": {"text": "Booking is by phone or Instagram DM", "url": PAGES[1]["url"], "quote": "call us or send a DM on Instagram"},
        "likely_objective": "Reduce the workload attached to the new hire",
        "reason_to_respond": "A new coordinator inherits phone and DM booking.",
        "vector": "capacity",
        "platform": "none",
    }
    return {**base, **kw}


def judge(r, max_age=90):
    return judge_to_signal(r, PAGES, TODAY, max_age)


def test_signal_led_when_signal_and_handoff_are_both_observed():
    rec, vector, signal_led = judge(raw())
    assert (vector, signal_led) == ("capacity", True)
    assert rec["current_signal"]["url"] == PAGES[0]["url"] and rec["relevant_handoff"]["url"] == PAGES[1]["url"]
    assert rec["evidence_strength"] == {"current_signal": "observed", "relevant_handoff": "observed", "likely_objective": "inference"}


@pytest.mark.parametrize("sig", [
    {"text": "t", "url": None, "date": "2026-10-28", "quote": "We are hiring a Front Desk Coordinator"},
    {"text": "t", "url": PAGES[0]["url"], "date": None, "quote": "We are hiring a Front Desk Coordinator"},
    {"text": "t", "url": PAGES[0]["url"], "date": "last month", "quote": "We are hiring a Front Desk Coordinator"},
])
def test_signal_without_url_or_a_real_date_is_dropped(sig):
    assert validate_signal(sig, TODAY, 90) is False
    rec, vector, signal_led = judge(raw(current_signal=sig))
    assert rec["current_signal"] is None and signal_led is False


def test_signal_older_than_max_age_is_dropped():
    old = {"text": "t", "url": PAGES[0]["url"], "date": "2026-06-01", "quote": "We are hiring a Front Desk Coordinator"}
    assert validate_signal(old, TODAY, 90) is False
    assert validate_signal({**old, "date": "2026-09-15"}, TODAY, 90) is True  # 56 days old


def test_future_dated_signal_is_dropped():
    assert validate_signal({"text": "t", "url": "u", "date": "2026-12-01", "quote": "q"}, TODAY, 90) is False


def test_quote_not_found_on_the_page_is_dropped_never_invented():
    rec, vector, signal_led = judge(raw(current_signal={**raw()["current_signal"], "quote": "We just opened a second location"}))
    assert rec["current_signal"] is None and signal_led is False


def test_url_that_was_not_fetched_is_dropped():
    rec, _, _ = judge(raw(relevant_handoff={**raw()["relevant_handoff"], "url": "https://elsewhere.com/x"}))
    assert rec["relevant_handoff"] is None


def test_no_valid_signal_but_valid_handoff_is_relevance_led_and_signal_stays_empty():
    rec, vector, signal_led = judge(raw(current_signal=None))
    assert rec["current_signal"] is None and signal_led is False and vector == "capacity"
    assert rec["evidence_strength"]["current_signal"] == "unknown"


def test_no_valid_handoff_means_no_vector_and_no_lane():
    rec, vector, signal_led = judge(raw(relevant_handoff=None))
    assert vector is None and signal_led is False and rec["relevant_handoff"] is None


@pytest.mark.parametrize("v", ["membership_growth", "after_hours_calls", "", None, "Capacity"])
def test_vector_must_be_one_of_the_three(v):
    rec, vector, signal_led = judge(raw(vector=v))
    assert vector is None and signal_led is False


def test_vectors_match_the_master_prompt_file():
    text = Path("MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md").read_text()
    for label in ("Conversion recovery", "Capacity", "Rebooking and retention"):
        assert label in text
    assert VECTORS == {"conversion_recovery", "capacity", "rebooking_retention"}
    assert "Observed fact" in SYSTEM and "No observed current signal" in SYSTEM or "observed" in SYSTEM.lower()


@pytest.mark.parametrize("html,expected", [
    ('<a href="https://app.zenoti.com/webstoreNew">Book</a>', "Zenoti"),
    ('<script src="https://www.vagaro.com/x.js"></script>', "Vagaro"),
    ('<a href="https://joinblvd.com/b/glow">Book</a>', "Boulevard"),
    ("<p>call us</p>", None),
])
def test_detect_platform(html, expected):
    assert detect_platform(html) == expected


def test_fetch_evidence_skips_missing_pages_caps_text_and_detects_platform():
    html = {"https://glow.com/": "<p>" + "x" * 20000 + "</p><a href='https://app.zenoti.com/x'>b</a>", "https://glow.com/careers": "<p>Hiring</p>"}
    ev = fetch_evidence({"domain": "glow.com"}, fetch=html.get)
    assert [p["url"] for p in ev["pages"]] == ["https://glow.com/", "https://glow.com/careers"]
    assert all(len(p["text"]) <= MAX_PAGE_CHARS for p in ev["pages"])
    assert ev["platform"] == "Zenoti"


@pytest.fixture
def enriched():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    items = [{"placeId": f"TEST_{i}", "title": f"Spa {i}", "website": f"https://glow{i}.com", "categories": ["Medical spa"], "state": "Texas"} for i in range(3)]
    db.table("leads").insert([{**place_to_lead(i, bid), "status": "enriched"} for i in items]).execute()
    yield db, bid
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("batches").delete().eq("id", bid).execute()


def row(db, i):
    return db.table("leads").select("*").eq("place_id", f"TEST_{i}").execute().data[0]


@pytest.mark.db
def test_run_signals_saves_the_record_and_marks_signalled(enriched):
    db, bid = enriched
    answers = {"glow0.com": raw(), "glow1.com": raw(current_signal=None), "glow2.com": raw(relevant_handoff=None)}
    out = run_signals(db, lambda s, p: answers[next(d for d in answers if d in p)], lambda lead: {"pages": PAGES, "platform": None}, bid, TODAY, 90)
    assert out == {"signal_led": 1, "relevance_led": 1, "no_handoff": 1}
    a, b, c = row(db, 0), row(db, 1), row(db, 2)
    assert (a["status"], a["vector"], a["signal_led"]) == ("signalled", "capacity", True) and a["signal"]["current_signal"]["date"] == "2026-10-28"
    assert (b["vector"], b["signal_led"], b["signal"]["current_signal"]) == ("capacity", False, None)
    assert (c["status"], c["vector"], c["signal_led"]) == ("signalled", None, False)
    assert run_signals(db, lambda s, p: pytest.fail("already signalled"), lambda lead: {"pages": PAGES, "platform": None}, bid, TODAY, 90) == {}


@pytest.mark.db
def test_lead_with_no_reachable_pages_is_recorded_without_calling_the_model(enriched):
    db, bid = enriched
    out = run_signals(db, lambda s, p: pytest.fail("no pages, no model call"), lambda lead: {"pages": [], "platform": None}, bid, TODAY, 90)
    assert out == {"no_handoff": 3} and row(db, 0)["status"] == "signalled" and row(db, 0)["vector"] is None


@pytest.mark.db
def test_model_failure_leaves_the_lead_enriched_for_a_retry(enriched):
    db, bid = enriched

    def boom(s, p):
        raise RuntimeError("llm down")

    out = run_signals(db, boom, lambda lead: {"pages": PAGES, "platform": None}, bid, TODAY, 90)
    assert out == {"llm_error": 3} and row(db, 0)["status"] == "enriched"
