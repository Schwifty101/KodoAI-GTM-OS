import pytest

from gtm.harvest import HarvestBudget, HarvestClient, harvest_finder

LEAD = {"name": "Galleria Aesthetics", "domain": "galleriaesthetics.com", "city": "Houston",
        "known": [{"first_name": "Marjon", "last_name": "Monfared", "position": "Owner", "email": None, "source": "search"}]}
LI = [{"title": "Marjon Monfared - Galleria", "link": "https://www.linkedin.com/in/marjon-monfared-a08420b6", "snippet": ""}]


def profile(first="Marjon", last="Monfared", company="Galleria Aesthetics and Wellness", emails=None):
    return {"firstName": first, "lastName": last, "currentPosition": [{"companyName": company}], "emails": emails or []}


def client(prof, balances=(20.0, 19.996), budget=1.0, status=200):
    """Fake HTTP: balance reads come from `balances` in order; the profile call returns `prof`."""
    bal, logs = list(balances), []

    def http(path, params, key):
        if path == "/users/my-api-user":
            return 200, {"usage": {"balance": bal.pop(0)}}
        return status, {"element": prof}

    return HarvestClient("k", budget, http=http, log=lambda usd, note: logs.append((round(usd, 4), note))), logs


GOOD = {"email": "m@galleria-test.example", "deliverable": True, "catchAllDomain": False, "qualityScore": 95, "status": "valid"}


def test_profile_cost_is_the_balance_drop_and_is_logged():
    c, logs = client(profile())
    c.profile("https://www.linkedin.com/in/x")
    assert logs == [(0.004, "profile:https://www.linkedin.com/in/x")] and round(c.spent, 4) == 0.004


def test_finder_returns_a_deliverable_email_for_the_right_person_at_the_right_company():
    c, _ = client(profile(emails=[GOOD]))
    out = harvest_finder(c, lambda q: LI)(LEAD)
    assert out == [{"email": "m@galleria-test.example", "first_name": "Marjon", "last_name": "Monfared", "position": "Owner",
                    "verification_status": "valid", "score": 95, "source": "harvest"}]


def test_catch_all_address_is_not_marked_valid():
    c, _ = client(profile(emails=[{**GOOD, "catchAllDomain": True}]))
    assert harvest_finder(c, lambda q: LI)(LEAD)[0]["verification_status"] == "unverified"


def test_wrong_company_is_rejected_even_when_the_name_matches():
    c, _ = client(profile(company="Edwards Lifesciences", emails=[GOOD]))
    assert harvest_finder(c, lambda q: LI)(LEAD) == []


def test_wrong_person_is_rejected():
    c, _ = client(profile(first="Maria", emails=[GOOD]))
    assert harvest_finder(c, lambda q: LI)(LEAD) == []


def test_no_known_owner_means_no_search_and_no_spend():
    c, logs = client(profile())
    assert harvest_finder(c, lambda q: pytest.fail("must not search"))({**LEAD, "known": []}) == [] and logs == []


def test_non_decision_maker_is_not_looked_up():
    lead = {**LEAD, "known": [{**LEAD["known"][0], "position": "Practice Manager"}]}
    c, logs = client(profile())
    assert harvest_finder(c, lambda q: pytest.fail("must not search"))(lead) == [] and logs == []


def test_no_linkedin_result_means_no_harvest_call():
    c, logs = client(profile())
    assert harvest_finder(c, lambda q: [{"title": "x", "link": "https://galleriaesthetics.com/about", "snippet": ""}])(LEAD) == [] and logs == []


def test_budget_cap_stops_lookups_without_failing_the_run():
    c, _ = client(profile(emails=[GOOD]), budget=0.0)
    assert harvest_finder(c, lambda q: LI)(LEAD) == []
    with pytest.raises(HarvestBudget):
        c.profile("https://www.linkedin.com/in/x")
