from gtm.researcher import research_owner_finder

LEAD = {"name": "Lumina Med Spa", "domain": "luminamedspa.com", "city": "Houston", "state": "TX", "address": "1 Main St", "website": "https://luminamedspa.com"}
URL = "https://luminamedspa.com/about"


def call(fn, /, **args):
    return [{"functionCall": {"name": fn, "args": args}}]


def ans(name, title, url=URL):
    return call("answer", name=name, title=title, evidence_url=url, quote="")


class Pool:
    def __init__(self, email=None):
        self.email, self.calls = email, []

    def email_finder(self, domain, first, last):
        self.calls.append((domain, first, last))
        return {"email": self.email, "first_name": first, "last_name": last} if self.email else None


def script(*steps):
    it = iter(steps)
    return lambda contents, last=False: next(it)


def run(text, answer, pool=None, lead=LEAD, url=URL, **kw):
    """fetch one page whose text is `text`, then answer"""
    pool = pool or Pool()
    llm = script(call("fetch_page", url=url), answer)
    f = research_owner_finder(pool, lambda q, n=6: [], lambda u: f"<p>{text}</p>", llm, **kw)
    return f(dict(lead)), pool


def test_accepts_credentialed_name_against_founder_text():
    got, _ = run("Welcome to Lumina Med Spa. Our founder, Dr. Liet N Le, started it.", ans("Dr. Liet N. Le, MD", "Owner"))
    assert [(c["first_name"], c["last_name"], c["source"], c["evidence_url"]) for c in got] == [("Liet", "Le", "research", URL)]


def test_founded_by_counts_as_founder_title():
    got, _ = run("Lumina Med Spa was founded in 2019 by Dr. Ernai Hernandez.", ans("Dr. Ernai Hernandez", "Medical Director"))
    assert got[0]["position"] == "Founder" and got[0]["last_name"] == "Hernandez"


def test_first_name_only_rejected():
    assert run("Lumina Med Spa owner Jazal welcomes you.", ans("Jazal", "Owner"))[0] == []


def test_name_not_in_fetched_text_rejected():
    assert run("Lumina Med Spa owner Jane Roe.", ans("Mary Smith", "Owner"))[0] == []


def test_medical_director_only_rejected():
    assert run("Lumina Med Spa. Dr. Mary Smith is our Medical Director.", ans("Mary Smith", "Medical Director"))[0] == []


def test_managing_member_rejected():
    assert run("Lumina Med Spa LLC. Mary Smith, Managing Member.", ans("Mary Smith", "Managing Member"))[0] == []


def test_directory_page_rejected():
    assert run("Lumina Med Spa owner Mary Smith. Other Spa owner Joe Bloggs.", ans("Mary Smith", "Owner", "https://www.yelp.com/search?find_desc=med+spa"),
               url="https://www.yelp.com/search?find_desc=med+spa")[0] == []


def test_unseen_evidence_url_rejected():
    assert run("Lumina Med Spa owner Mary Smith.", ans("Mary Smith", "Owner", "https://other.com/x"))[0] == []


def test_skips_without_any_call_when_owner_known():
    def boom(*a, **k):
        raise AssertionError("spent")
    f = research_owner_finder(Pool(), boom, boom, boom)
    assert f({**LEAD, "known": [{"first_name": "A", "last_name": "B", "position": "Owner"}]}) == []


def test_hunter_email_attached():
    got, pool = run("Lumina Med Spa owner Mary Smith.", ans("Mary Smith", "Owner"), pool=Pool("mary@luminamedspa.com"))
    assert got[0]["email"] == "mary@luminamedspa.com" and got[0]["source"] == "research+hunter" and pool.calls == [("luminamedspa.com", "Mary", "Smith")]


def test_run_budget_stops_spending():
    searches = []
    f = research_owner_finder(Pool(), lambda q, n=6: searches.append(q) or [], lambda u: None, lambda c, last=False: call("web_search", query="x") if not last else call("answer"), budget=2)
    f(dict(LEAD)); f(dict(LEAD)); f(dict(LEAD))
    assert len(searches) == 2


def test_gemini_step_raises_budget_exceeded_before_any_http_request(monkeypatch):
    import pytest

    from gtm import budget, researcher

    def no_http(*a, **k):
        raise AssertionError("http called")

    monkeypatch.setattr(budget, "gemini_allowed", lambda db=None, today=None: False)
    monkeypatch.setattr(researcher.httpx, "post", no_http)
    with pytest.raises(budget.BudgetExceeded):
        researcher.gemini_step([])
