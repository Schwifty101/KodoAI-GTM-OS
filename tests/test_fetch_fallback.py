import httpx
import pytest

from gtm import apify, search, sitescrape
from gtm.budget import BudgetExceeded

BIG = "<html><body>" + "<p>Dr Jane Doe is the founder of our clinic.</p>" * 20 + "</body></html>"
CHALLENGE = "<html><head><script>x</script></head><body><h1>Just a moment...</h1></body></html>"
SHELL = "<html><body><div id=root></div><script src=app.js></script></body></html>"


def resp(status=200, text=BIG, ctype="text/html", content=None):
    return httpx.Response(status, text=text, headers={"content-type": ctype}, content=content, request=httpx.Request("GET", "https://x.com"))


def fetch(monkeypatch, r):
    def get(*a, **k):
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(sitescrape.httpx, "get", get)
    return sitescrape.fetch_page("https://x.com")


@pytest.mark.parametrize("r,outcome", [
    (resp(), "ok"),
    (resp(403), "blocked"), (resp(429), "blocked"), (resp(503), "blocked"),
    (resp(text=CHALLENGE), "blocked"), (resp(text=SHELL), "blocked"),
    (resp(404), "gone"), (resp(410), "gone"),
    (httpx.ConnectTimeout("t"), "gone"), (resp(ctype="application/pdf"), "gone"),
    (resp(content=b"<html>" + b"a" * 1_500_001), "gone"),
])
def test_fetch_page_outcome(monkeypatch, r, outcome):
    assert fetch(monkeypatch, r)[1] == outcome


@pytest.fixture
def calls(monkeypatch):
    c = []
    monkeypatch.setattr(search, "serper_scrape", lambda u: c.append("serper") or None)
    monkeypatch.setattr(apify, "crawl_page", lambda u: c.append("apify") or None)
    monkeypatch.setattr("gtm.settings_store.setting", lambda k, db=None: True)
    return c


def test_fallback_not_called_when_direct_fetch_works(monkeypatch, calls):
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (BIG, "ok"))
    assert sitescrape.fetch_with_fallback("u") == BIG and calls == []


@pytest.mark.parametrize("out", ["gone"])
def test_fallback_not_called_when_page_is_gone(monkeypatch, calls, out):
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (None, out))
    assert sitescrape.fetch_with_fallback("u") is None and calls == []


def test_fallback_not_called_when_setting_off(monkeypatch, calls):
    monkeypatch.setattr("gtm.settings_store.setting", lambda k, db=None: False)
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (None, "blocked"))
    assert sitescrape.fetch_with_fallback("u") is None and calls == []


def test_fallback_tries_serper_then_apify_when_blocked(monkeypatch, calls):
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (None, "blocked"))
    monkeypatch.setattr(apify, "crawl_page", lambda u: calls.append("apify") or "x" * 300)
    assert sitescrape.fetch_with_fallback("u") == "x" * 300 and calls == ["serper", "apify"]


def test_fallback_rejects_a_challenge_page_from_the_service(monkeypatch, calls):
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (None, "blocked"))
    monkeypatch.setattr(search, "serper_scrape", lambda u: "Just a moment... " + "x" * 300)
    assert sitescrape.fetch_with_fallback("u") is None


def test_fallback_swallows_service_errors_but_not_budget_exceeded(monkeypatch, calls):
    monkeypatch.setattr(sitescrape, "fetch_page", lambda u: (None, "blocked"))

    def boom(u):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(search, "serper_scrape", boom)
    monkeypatch.setattr(apify, "crawl_page", boom)
    assert sitescrape.fetch_with_fallback("u") is None

    def over(u):
        raise BudgetExceeded("cap")
    monkeypatch.setattr(search, "serper_scrape", over)
    with pytest.raises(BudgetExceeded):
        sitescrape.fetch_with_fallback("u")


def test_malformed_url_is_gone_not_a_crash(monkeypatch):
    assert fetch(monkeypatch, httpx.InvalidURL("bad")) == (None, "gone")
