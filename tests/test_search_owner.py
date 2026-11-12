from gtm.owner_search import search_owner_finder, validate_owner

RENOVE = [
    {"title": "About Rénove Medical Spa", "link": "https://renovemedicalspa.com/about-us/", "snippet": "Our med spa in Kingwood."},
    {"title": "Dr. Michelle Parsons - Owner/Physician at Renove Med Spa", "link": "https://www.linkedin.com/in/dr-michelle-parsons-b8894b81", "snippet": "Owner/Physician at Renove Med Spa. Kingwood, Texas."},
]
BUSINESS = {"name": "Renove Medical Spa", "domain": "renovemedicalspa.com", "city": "Kingwood"}


def test_validate_owner_accepts_a_named_owner_in_a_result_about_this_business():
    got = validate_owner({"name": "Michelle Parsons", "title": "Owner/Physician", "url": RENOVE[1]["link"]}, RENOVE, BUSINESS)
    assert got == {"first_name": "Michelle", "last_name": "Parsons", "position": "Owner/Physician", "url": RENOVE[1]["link"]}


def test_validate_owner_rejects_a_different_business_with_a_similar_name():
    ps = {"name": "PS Medical Spa", "domain": "psmedspa.com", "city": "Houston"}
    res = [{"title": "Philip Hewitson - Founder, Medical Spa Owners Network", "link": "https://www.linkedin.com/in/philip-hewitson", "snippet": "Founder"}]
    assert validate_owner({"name": "Philip Hewitson", "title": "Founder", "url": res[0]["link"]}, res, ps) is None


def test_validate_owner_rejects_a_name_the_model_made_up():
    assert validate_owner({"name": "Dana Whitfield", "title": "Owner", "url": RENOVE[1]["link"]}, RENOVE, BUSINESS) is None


def test_validate_owner_rejects_a_title_that_is_not_a_decision_maker():
    res = [{"title": "Sam Ortiz - Medical Director at Renove Med Spa", "link": "https://x.com/sam", "snippet": "Renove"}]
    assert validate_owner({"name": "Sam Ortiz", "title": "Medical Director", "url": "https://x.com/sam"}, res, BUSINESS) is None


def test_validate_owner_rejects_nulls_and_unknown_urls():
    assert validate_owner({"name": None, "title": None, "url": None}, RENOVE, BUSINESS) is None
    assert validate_owner({"name": "Michelle Parsons", "title": "Owner", "url": "https://nope.com"}, RENOVE, BUSINESS) is None


class FakePool:
    def __init__(self, found=True):
        self.found, self.asked = found, []

    def email_finder(self, domain, first, last):
        self.asked.append((domain, first, last))
        if not self.found:
            return None
        return {"email": "michelle@renovemedicalspa.com", "first_name": first, "last_name": last, "position": None, "verification_status": "valid", "score": 90, "source": "hunter"}


def test_finder_searches_owner_of_domain_then_asks_hunter_for_the_email():
    queries = []

    def search(q):
        queries.append(q)
        return RENOVE

    llm = lambda s, p: {"name": "Michelle Parsons", "title": "Owner/Physician", "url": RENOVE[1]["link"]}  # noqa: E731
    pool = FakePool()
    out = search_owner_finder(pool, search, llm)(BUSINESS)
    assert queries == ["owner of renovemedicalspa.com"]
    assert pool.asked == [("renovemedicalspa.com", "Michelle", "Parsons")]
    assert out == [{"email": "michelle@renovemedicalspa.com", "first_name": "Michelle", "last_name": "Parsons", "position": "Owner/Physician",
                    "verification_status": "valid", "score": 90, "source": "search+hunter", "evidence_url": RENOVE[1]["link"]}]


def test_finder_keeps_the_validated_name_when_hunter_finds_no_email():
    out = search_owner_finder(FakePool(found=False), lambda q: RENOVE, lambda s, p: {"name": "Michelle Parsons", "title": "Owner/Physician", "url": RENOVE[1]["link"]})(BUSINESS)
    assert out == [{"email": None, "first_name": "Michelle", "last_name": "Parsons", "position": "Owner/Physician", "source": "search",
                    "evidence_url": RENOVE[1]["link"]}]


def test_finder_costs_no_hunter_credit_when_no_valid_owner_is_found():
    pool = FakePool()
    out = search_owner_finder(pool, lambda q: RENOVE, lambda s, p: {"name": None, "title": None, "url": None})(BUSINESS)
    assert out == [] and pool.asked == []


def test_finder_returns_nothing_when_search_returns_nothing():
    pool = FakePool()
    assert search_owner_finder(pool, lambda q: [], lambda s, p: pytest.fail("no results, no model call"))(BUSINESS) == [] and pool.asked == []


import pytest  # noqa: E402
