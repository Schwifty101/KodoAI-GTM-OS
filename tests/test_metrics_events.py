"""Plan 6 Task 1: migration 0017 (touches.outcome_at, leads.booked_at, view cost_daily). TEST_mev leads, TEST batch, batch_no left null."""
import httpx
import pytest
from postgrest.exceptions import APIError

from gtm.config import get_settings
from gtm.db import get_db
from gtm.scrape import new_batch

pytestmark = pytest.mark.db
NOTE = "TEST_mev"  # marks every cost row this file writes, so cleanup finds lead-only and no-run rows too
DAY = "2020-01-10"  # far from any real spend, so a no-run group on these days holds only our rows


@pytest.fixture(autouse=True)
def _migration_0017_applied():
    """Runs before any insert (autouse fixtures come first): a read-only probe, so a skipped run writes nothing."""
    try:
        get_db().table("touches").select("outcome_at").limit(1).execute()
    except APIError as e:
        if e.code != "42703":  # undefined column; anything else is a real failure
            raise
        pytest.skip("migration 0017 not applied")


@pytest.fixture
def ev():
    db = get_db()
    bid = new_batch(db, "TEST metrics events", "TX", ["x"])
    try:
        yield db, bid
    finally:
        db.table("cost_log").delete().eq("note", NOTE).execute()
        db.table("leads").delete().like("place_id", "TEST_mev%").execute()  # touches go with their lead
        db.table("batches").delete().eq("id", bid).execute()


def lead(db, bid, n, **kw):
    return db.table("leads").insert({"place_id": f"TEST_mev{n}", "name": f"Spa {n}", "batch_id": bid, **kw}).execute().data[0]["id"]


def touch(db, lid, no=1, **kw):
    return db.table("touches").insert({"lead_id": lid, "touch_no": no, "status": "sent", **kw}).execute().data[0]


def cost(db, provider, units, usd, at, **kw):
    db.table("cost_log").insert({"provider": provider, "units": units, "usd": usd, "created_at": at, "note": NOTE, **kw}).execute()


def daily(db, **eq):
    q = db.table("cost_daily").select("*")
    for k, v in eq.items():
        q = q.is_(k, "null") if v is None else q.eq(k, v)
    return q.order("day").order("provider").execute().data


def test_outcome_at_is_set_when_outcome_first_set(ev):
    db, bid = ev
    lid = lead(db, bid, 1)
    assert touch(db, lid, 1, outcome="positive")["outcome_at"] is not None  # insert with an outcome
    t2 = touch(db, lid, 2)
    assert t2["outcome_at"] is None
    got = db.table("touches").update({"outcome": "negative"}).eq("id", t2["id"]).execute().data[0]  # update from null
    assert got["outcome_at"] is not None


def test_outcome_at_is_not_overwritten_when_outcome_changes(ev):
    db, bid = ev
    t = touch(db, lead(db, bid, 1), 1, outcome="positive")
    got = db.table("touches").update({"outcome": "negative"}).eq("id", t["id"]).execute().data[0]
    assert got["outcome"] == "negative" and got["outcome_at"] == t["outcome_at"]


def test_outcome_at_stays_null_without_an_outcome(ev):
    db, bid = ev
    t = touch(db, lead(db, bid, 1), 1)
    assert t["outcome_at"] is None
    got = db.table("touches").update({"status": "scheduled", "scheduled_for": "2020-01-10"}).eq("id", t["id"]).execute().data[0]
    assert got["outcome"] is None and got["outcome_at"] is None


def test_booked_at_is_set_when_status_becomes_booked_and_kept(ev):
    db, bid = ev
    lid = lead(db, bid, 1, status="replied")
    assert db.table("leads").select("booked_at").eq("id", lid).execute().data[0]["booked_at"] is None
    first = db.table("leads").update({"status": "booked"}).eq("id", lid).execute().data[0]["booked_at"]
    assert first is not None
    later = db.table("leads").update({"city": "Austin"}).eq("id", lid).execute().data[0]  # a later update keeps it
    assert later["booked_at"] == first


def test_cost_daily_groups_by_utc_day_provider_and_run(ev):
    db, bid = ev
    cost(db, "apify", 10, 0.5, "2020-01-10T10:00:00+00:00", batch_id=bid)
    cost(db, "apify", 20, 0.25, "2020-01-10T11:00:00+00:00", batch_id=bid)  # same day, provider and run: one summed row
    cost(db, "hunter", 3, None, "2020-01-10T11:00:00+00:00", batch_id=bid)  # no dollars: usd 0, never null
    cost(db, "apify", 1, 0.1, "2020-01-11T23:30:00+00:00", batch_id=bid)
    cost(db, "apify", 2, 0.2, "2020-01-12T00:30:00+00:00", batch_id=bid)  # an hour later, the next UTC day
    rows = [(r["day"], r["provider"], r["run_id"], float(r["units"]), float(r["usd"])) for r in daily(db, run_id=bid)]
    assert rows == [
        ("2020-01-10", "apify", bid, 30.0, 0.75),
        ("2020-01-10", "hunter", bid, 3.0, 0.0),
        ("2020-01-11", "apify", bid, 1.0, 0.1),
        ("2020-01-12", "apify", bid, 2.0, 0.2),
    ]


def test_cost_daily_attributes_a_lead_only_row_to_the_leads_run(ev):
    db, bid = ev
    lid = lead(db, bid, 1)
    cost(db, "hunter", 2, None, f"{DAY}T10:00:00+00:00", lead_id=lid)  # no batch_id: follows the lead's batch
    rows = daily(db, run_id=bid)
    assert [(r["day"], r["provider"], float(r["units"])) for r in rows] == [(DAY, "hunter", 2.0)]


def test_cost_daily_keeps_a_row_with_no_batch_or_lead_as_null_run(ev):
    db, _ = ev
    cost(db, "apify", 1, 0.1, "2020-01-13T12:00:00+00:00")
    rows = daily(db, run_id=None, day="2020-01-13")
    assert [(r["provider"], r["run_id"], float(r["units"]), float(r["usd"])) for r in rows] == [("apify", None, 1.0, 0.1)]


def test_cost_daily_is_empty_for_a_signed_out_visitor(ev):
    db, bid = ev
    cost(db, "apify", 1, 0.1, f"{DAY}T10:00:00+00:00", batch_id=bid)
    assert daily(db, run_id=bid)  # the row is there for the secret key
    s = get_settings()
    r = httpx.get(f"{s.supabase_url}/rest/v1/cost_daily", headers={"apikey": s.supabase_publishable_key, "Authorization": f"Bearer {s.supabase_publishable_key}"}, timeout=30)
    assert r.status_code == 200 and r.json() == []  # security_invoker: RLS on cost_log still applies
