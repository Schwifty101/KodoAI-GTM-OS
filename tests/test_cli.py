import argparse

import pytest

from gtm import budget, cli


def test_blocked_scrape_creates_no_batch(monkeypatch):
    def blocked(*a, **k):
        raise budget.BudgetExceeded("cap")

    monkeypatch.setattr(budget, "require", blocked)
    monkeypatch.setattr(cli, "get_db", lambda: pytest.fail("db touched"))
    monkeypatch.setattr(cli, "new_batch", lambda *a, **k: pytest.fail("batch created"))
    a = argparse.Namespace(query=None, max_places=5, city="X", state="TX", max_usd=1.0)
    with pytest.raises(budget.BudgetExceeded):
        cli.cmd_scrape(a)
