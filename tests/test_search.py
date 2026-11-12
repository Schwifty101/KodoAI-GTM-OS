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
