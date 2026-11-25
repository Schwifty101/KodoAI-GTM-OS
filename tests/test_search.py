import pytest

import gtm.search as search
from gtm.hunter import OutOfCredits


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_spent_serper_key_raises_out_of_credits_not_a_generic_error(monkeypatch):
    monkeypatch.setattr(search.httpx, "post", lambda *a, **k: Resp(400, {"message": "Not enough credits", "statusCode": 400}))
    with pytest.raises(OutOfCredits):
        search.serper_search("owner of x.com")


def test_results_are_mapped_to_title_link_snippet(monkeypatch):
    body = {"organic": [{"title": "T", "link": "https://a.com", "snippet": "S", "position": 1}]}
    monkeypatch.setattr(search.httpx, "post", lambda *a, **k: Resp(200, body))
    monkeypatch.setattr(search, "log_cost", lambda *a, **k: None)
    assert search.serper_search("q") == [{"title": "T", "link": "https://a.com", "snippet": "S"}]


def test_serper_search_raises_budget_exceeded_before_any_request(monkeypatch):
    from gtm import budget

    def deny(*a, **k):
        raise budget.BudgetExceeded("serper cap")

    monkeypatch.setattr(budget, "require", deny)
    monkeypatch.setattr(search.httpx, "post", lambda *a, **k: pytest.fail("no request when over budget"))
    with pytest.raises(budget.BudgetExceeded):
        search.serper_search("q")


def test_spent_first_key_falls_to_second_and_stays_retired(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(search, "get_settings", lambda: SimpleNamespace(serper_keys=["k1", "k2"], serper_api_key="k1"))
    monkeypatch.setattr(search, "_dead", set())
    used = []

    def post(url, headers, **k):
        used.append(headers["X-API-KEY"])
        return Resp(400, {"message": "Not enough credits"}) if headers["X-API-KEY"] == "k1" else Resp(200, {})

    assert search.serper_post("u", post=post, json={}).status_code == 200
    search.serper_post("u", post=post, json={})
    assert used == ["k1", "k2", "k2"]
    monkeypatch.setattr(search, "_dead", {"k1", "k2"})  # all spent: the last key's answer reaches the caller's OutOfCredits check
    assert search.serper_post("u", post=post, json={}).status_code == 200
