import pytest

from gtm.settings_store import DEFAULTS


@pytest.fixture(autouse=True)
def _no_budget_db(monkeypatch):
    """Unit tests of paid calls never read the real database through the budget gate."""
    monkeypatch.setattr("gtm.budget._cost_rows", lambda db, provider, since: [])
    monkeypatch.setattr("gtm.budget.setting", lambda key, db=None: DEFAULTS[key])
