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


@pytest.mark.parametrize("command", ["replies", "followups", "send"])
def test_reply_checks_use_reply_model(monkeypatch, command):
    db = object()
    seen = []
    monkeypatch.setattr(cli, "get_db", lambda: db)
    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "run_replies", lambda db, gmail, llm: seen.append(llm))
    monkeypatch.setattr(cli, "run_followups", lambda *args: 0)
    monkeypatch.setattr(cli, "send_with_reply_check", lambda db, gmail, llm, *args, **kw: seen.append(llm))
    getattr(cli, f"cmd_{command}")(argparse.Namespace(confirm=True, anytime=False))
    assert seen == [cli.complete_reply_json]
