import httpx
import pytest

from gtm.config import get_settings
from gtm.db import get_db
from gtm.scrape import new_batch, place_to_lead

SIG = {"current_signal": None, "relevant_handoff": {"text": "t", "url": "u", "quote": "q"}}


def seed(db, bid):
    """8 leads at different points: L1 rejected by cleaning ... L8 booked."""
    def lead(n, status, **kw):
        item = {"placeId": f"TEST_m{n}", "title": f"Spa {n}", "website": f"https://m{n}.com", "categories": ["Medical spa"], "state": "Texas"}
        defaults = {"signal": None, "signal_led": False, "owner_email": None, "email_verified": None, "reject_reason": None}  # bulk insert needs identical keys
        return {**place_to_lead(item, bid), "status": status, **defaults, **kw}

    mail = lambda n: {"owner_email": f"d@m{n}.com", "email_verified": True}  # noqa: E731
    rows = [
        lead(1, "rejected", reject_reason="not_us"),
        lead(2, "no_buyer"),
        lead(3, "signalled", signal=SIG, **mail(3)),
        lead(4, "drafted", signal=SIG, signal_led=True, **mail(4)),
        lead(5, "sent", signal=SIG, **mail(5)),
        lead(6, "bounced", signal=SIG, **mail(6)),
        lead(7, "replied", signal=SIG, **mail(7)),
        lead(8, "booked", signal=SIG, signal_led=True, **mail(8)),
    ]
    ids = {r["place_id"]: r["id"] for r in db.table("leads").insert(rows).execute().data}
    touch = lambda n, status, **kw: {"lead_id": ids[f"TEST_m{n}"], "touch_no": 1, "status": status, "outcome": None, **kw}  # noqa: E731
    db.table("touches").insert([
        touch(4, "drafted"), touch(5, "sent"), touch(6, "sent"), touch(7, "sent", outcome="positive"), touch(8, "sent"),
    ]).execute()
    db.table("cost_log").insert([
        {"provider": "apify", "units": 100, "usd": 0.5, "batch_id": bid}, {"provider": "hunter", "units": 3, "usd": None, "batch_id": bid},
        {"provider": "serper", "units": 2, "usd": None, "batch_id": bid},
    ]).execute()


@pytest.fixture
def batch():
    db = get_db()
    bid = new_batch(db, "Metrics", "TX", ["x"])
    try:  # a failed seed must still clean up
        seed(db, bid)
        yield db, bid
    finally:
        db.table("cost_log").delete().eq("batch_id", bid).execute()
        db.table("leads").delete().like("place_id", "TEST_m%").execute()
        db.table("batches").delete().eq("id", bid).execute()


@pytest.mark.db
def test_batch_metrics_counts_the_funnel_and_costs(batch):
    db, bid = batch
    m = db.table("batch_metrics").select("*").eq("batch_id", bid).execute().data[0]
    assert (m["scraped"], m["cleaned"], m["enriched"], m["signalled"], m["signal_led"]) == (8, 7, 6, 6, 2)
    assert (m["drafted"], m["sent"], m["bounced"], m["replied"], m["positive"], m["booked"]) == (5, 4, 1, 2, 2, 1)
    assert float(m["apify_usd"]) == 0.5 and float(m["hunter_credits"]) == 3 and float(m["serper_queries"]) == 2
    assert float(m["apify_usd_per_lead"]) == pytest.approx(0.5 / 8)
    assert float(m["apify_usd_per_verified_email"]) == pytest.approx(0.5 / 6)
    assert float(m["hunter_credits_per_verified_email"]) == pytest.approx(3 / 6)


@pytest.mark.db
def test_an_empty_batch_has_zero_counts_and_null_ratios_not_a_division_error():
    db = get_db()
    bid = new_batch(db, "Empty", "TX", ["x"])
    try:
        m = db.table("batch_metrics").select("*").eq("batch_id", bid).execute().data[0]
        assert (m["scraped"], m["enriched"], m["sent"]) == (0, 0, 0)
        assert m["apify_usd_per_lead"] is None and m["apify_usd_per_verified_email"] is None
    finally:
        db.table("batches").delete().eq("id", bid).execute()


@pytest.mark.db
def test_signed_out_visitors_see_nothing_through_the_view(batch):
    s = get_settings()
    r = httpx.get(f"{s.supabase_url}/rest/v1/batch_metrics", headers={"apikey": s.supabase_publishable_key, "Authorization": f"Bearer {s.supabase_publishable_key}"}, timeout=30)
    assert r.status_code == 200 and r.json() == []  # security_invoker: RLS on the tables still applies
