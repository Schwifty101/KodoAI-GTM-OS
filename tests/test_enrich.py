import pytest

from gtm.db import get_db
from gtm.enrich import is_decision_maker, is_role_email, pick_buyer, run_enrich
from gtm.hunter import OutOfCredits
from gtm.scrape import new_batch, place_to_lead


@pytest.mark.parametrize("email", ["info@spa.com", "contact@spa.com", "hello@spa.com", "office@spa.com", "admin@spa.com",
                                   "support@spa.com", "appointments@spa.com", "frontdesk@spa.com", "INFO@spa.com"])
def test_role_emails_never_qualify(email):
    assert is_role_email(email)


def test_personal_email_is_not_role():
    assert not is_role_email("dana@spa.com") and not is_role_email("dana.whitfield@spa.com")


@pytest.mark.parametrize("title", ["Founder & CEO", "Owner", "Co-Owner", "Founder", "CEO", "President", "Owner/Operator", "Owner & Medical Director", "COO", "Chief Operating Officer", "Executive Director"])
def test_decision_maker_titles(title):
    assert is_decision_maker(title)


@pytest.mark.parametrize("title", ["Practice Manager", "Office Manager", "Medical Director", "Aesthetician", "Vice President of Operations", "Franchise Owner", "General Manager", "Executive Assistant to the CEO", "Assistant to the Owner", "Owner's Assistant", "Former Owner", "Retired Founder", "Board Advisor", "Ex-CEO", "Marketing Associate", None, ""])
def test_not_decision_maker_titles(title):
    assert not is_decision_maker(title)


def cand(**kw):
    return {"email": "dana@spa.com", "first_name": "Dana", "last_name": "W", "position": "Owner", "verification_status": "valid", "score": 90, "source": "hunter", **kw}


def test_pick_buyer_takes_verified_decision_maker():
    assert pick_buyer([cand()])["email"] == "dana@spa.com"


@pytest.mark.parametrize("bad", [
    [cand(email="info@spa.com")],
    [cand(verification_status="accept_all")],
    [cand(verification_status="unknown")],
    [cand(position=None)],
    [cand(position="Practice Manager")],
    [cand(email=None)],
    [cand(score=79)],
    [cand(score=None)],
    [],
])
def test_pick_buyer_rejects_role_unverified_untitled_or_non_decision_maker(bad):
    assert pick_buyer(bad) is None


def test_pick_buyer_accepts_score_exactly_80():
    assert pick_buyer([cand(score=80)])


def test_pick_buyer_prefers_most_senior():
    a, b = cand(email="a@spa.com", position="Co-Owner"), cand(email="b@spa.com", position="Founder & CEO")
    assert pick_buyer([a, b])["email"] == "b@spa.com"


@pytest.fixture
def cleaned():
    db = get_db()
    bid = new_batch(db, "A", "TX", ["x"])
    items = [{"placeId": f"TEST_{i}", "title": f"Spa {i}", "website": f"https://spa{i}.com", "categoryName": "Medical spa",
              "categories": ["Medical spa"], "state": "Texas"} for i in range(3)]
    db.table("leads").insert([{**place_to_lead(i, bid), "status": "cleaned"} for i in items]).execute()
    yield db, bid
    db.table("leads").delete().like("place_id", "TEST_%").execute()
    db.table("cost_log").delete().eq("batch_id", bid).execute()
    db.table("batches").delete().eq("id", bid).execute()


def row(db, i):
    return db.table("leads").select("*").eq("place_id", f"TEST_{i}").execute().data[0]


@pytest.mark.db
def test_failed_lead_is_no_buyer_and_not_rebought(cleaned):
    db, bid = cleaned
    calls = []

    def finder(lead):
        domain = lead["domain"]
        calls.append(domain)
        return [cand(email="info@" + domain)] if domain == "spa0.com" else [cand(email="dana@" + domain, source="site+hunter")]

    counts = run_enrich(db, [finder], bid)
    assert counts == {"enriched": 2, "no_buyer": 1}
    assert row(db, 0)["status"] == "no_buyer"
    r = row(db, 1)
    assert (r["status"], r["owner_email"], r["owner_name"], r["owner_title"], r["email_source"], r["email_verified"]) == (
        "enriched", "dana@spa1.com", "Dana W", "Owner", "site+hunter", True)
    n = len(calls)
    assert run_enrich(db, [finder], bid) == {} and len(calls) == n  # second run makes zero finder calls


@pytest.mark.db
def test_next_finder_runs_only_when_previous_finds_nothing(cleaned):
    db, bid = cleaned
    first, second = [], []

    def f1(lead):
        first.append(lead["domain"])
        return [cand(email="dana@" + lead["domain"])] if lead["domain"] == "spa0.com" else []

    def f2(lead):
        second.append(lead["domain"])
        return []

    run_enrich(db, [f1, f2], bid)
    assert sorted(first) == ["spa0.com", "spa1.com", "spa2.com"] and sorted(second) == ["spa1.com", "spa2.com"]


@pytest.mark.db
def test_out_of_credits_stops_the_run_and_leaves_leads_cleaned(cleaned):
    db, bid = cleaned

    def finder(lead):
        raise OutOfCredits("all keys spent")

    counts = run_enrich(db, [finder], bid)
    assert counts == {"out_of_credits": 3}
    assert all(row(db, i)["status"] == "cleaned" for i in range(3))  # not mislabelled no_buyer


@pytest.mark.db
def test_limit_caps_how_many_leads_are_processed(cleaned):
    db, bid = cleaned
    run_enrich(db, [lambda lead: []], bid, limit=1)
    assert sorted(row(db, i)["status"] for i in range(3)) == ["cleaned", "cleaned", "no_buyer"]


@pytest.mark.db
def test_failed_lead_keeps_the_owner_it_found_but_stays_no_buyer(cleaned):
    db, bid = cleaned
    named = {"email": "dana@spa0.com", "first_name": "Dana", "last_name": "W", "position": "Owner", "verification_status": "accept_all", "score": 99, "source": "search+hunter"}
    run_enrich(db, [lambda lead: [named] if lead["domain"] == "spa0.com" else []], bid)
    r = row(db, 0)
    assert (r["status"], r["owner_name"], r["owner_title"], r["owner_email"], r["email_verified"]) == ("no_buyer", "Dana W", "Owner", "dana@spa0.com", False)
    assert row(db, 1)["owner_name"] is None


@pytest.mark.db
def test_role_email_is_not_saved_but_the_name_is(cleaned):
    db, bid = cleaned
    named = {"email": "info@spa0.com", "first_name": "Dana", "last_name": "W", "position": "Owner", "verification_status": "valid", "score": 99, "source": "hunter"}
    run_enrich(db, [lambda lead: [named] if lead["domain"] == "spa0.com" else []], bid)
    assert (row(db, 0)["owner_name"], row(db, 0)["owner_email"]) == ("Dana W", None)


@pytest.mark.db
def test_retry_no_buyer_reruns_failed_leads_and_later_finders_see_saved_and_earlier_names(cleaned):
    db, bid = cleaned
    run_enrich(db, [lambda lead: [{"email": None, "first_name": "Dana", "last_name": "W", "position": "Owner", "source": "site"}]], bid)
    assert row(db, 0)["status"] == "no_buyer"
    got = []

    def later(lead):
        got.append([k["first_name"] for k in lead["known"]])
        return [cand(email="dana@" + lead["domain"])]

    assert run_enrich(db, [later], bid) == {}  # not retried by default
    assert run_enrich(db, [later], bid, retry_no_buyer=True) == {"enriched": 3}
    assert got == [["Dana"]] * 3  # the owner saved on the lead is handed to the finder


def test_site_finder_keeps_the_name_when_hunter_finds_no_email():
    from gtm.enrich import site_owner_finder

    class NoEmail:
        def email_finder(self, domain, first, last):
            return None

    html = "<h3>Dana Whitfield</h3><p>Founder & CEO</p>"
    out = site_owner_finder(NoEmail(), fetch=lambda url: html)({"domain": "glow.com"})
    assert out == [{"email": None, "first_name": "Dana", "last_name": "Whitfield", "position": "Founder & CEO", "source": "site"}]


@pytest.mark.db
def test_retry_that_finds_nothing_keeps_the_email_saved_earlier(cleaned):
    db, bid = cleaned
    named = {"email": "dana@spa0.com", "first_name": "Dana", "last_name": "W", "position": "Owner", "verification_status": "accept_all", "score": 73, "source": "search+hunter"}
    run_enrich(db, [lambda lead: [named] if lead["domain"] == "spa0.com" else []], bid)
    run_enrich(db, [lambda lead: []], bid, retry_no_buyer=True)
    assert (row(db, 0)["owner_name"], row(db, 0)["owner_email"], row(db, 0)["status"]) == ("Dana W", "dana@spa0.com", "no_buyer")
