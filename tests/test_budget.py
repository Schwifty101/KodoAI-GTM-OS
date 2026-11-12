from datetime import date, datetime, timezone

import pytest

from gtm import budget
from gtm.settings_store import DEFAULTS

REAL_COST_ROWS = budget._cost_rows  # conftest patches the attribute per test
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


def utc(y, m, d, h=1):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


@pytest.fixture
def world(monkeypatch):
    """rows: list of (provider, units, usd, created_at); overrides: settings."""
    w = {"rows": [], "set": {}}
    monkeypatch.setattr(budget, "setting", lambda k, db=None: w["set"].get(k, DEFAULTS[k]))
    monkeypatch.setattr(budget, "_cost_rows", lambda db, p, since: [
        {"units": u, "usd": c, "created_at": t} for pr, u, c, t in w["rows"] if pr == p and t >= since])
    return w


def test_require_passes_under_cap(world):
    world["rows"] = [("serper", 699, None, utc(2026, 11, 12))]
    budget.require("serper", 1, now=NOW)


def test_require_raises_over_cap(world):
    world["rows"] = [("serper", 699, None, utc(2026, 11, 12))]
    with pytest.raises(budget.BudgetExceeded):
        budget.require("serper", 2, now=NOW)


def test_yesterday_spend_not_counted(world):
    world["rows"] = [("serper", 700, None, utc(2026, 11, 11, 23))]
    budget.require("serper", 1, now=NOW)


def test_cap_zero_blocks_all_spend(world):
    world["set"]["cap_hunter_credits_day"] = 0
    with pytest.raises(budget.BudgetExceeded):
        budget.require("hunter", 1, now=NOW)


def test_gemini_allowed_within_credit(world):
    assert budget.gemini_allowed(today=date(2026, 11, 12))


def test_gemini_blocked_after_credit_end_when_paid_off(world):
    assert not budget.gemini_allowed(today=date(2027, 2, 10))


def test_gemini_blocked_when_credit_exhausted(world):
    world["rows"] = [("gemini", 1, 298.0, utc(2026, 11, 13))]
    assert budget.credit_remaining_usd(now=NOW) == 0
    assert not budget.gemini_allowed(today=date(2026, 12, 1))


def test_spend_before_balance_date_ignored(world):
    world["rows"] = [("gemini", 1, 50.0, utc(2026, 11, 11)), ("gemini", 1, 8.0, utc(2026, 11, 12))]
    assert budget.credit_remaining_usd(now=NOW) == 290


def test_paid_gemini_allowed_after_end_only_under_monthly_cap(world):
    world["set"].update(allow_paid_gemini=True, paid_gemini_monthly_cap_usd=2.0)
    world["rows"] = [("gemini", 1, 1.0, utc(2027, 2, 10))]
    assert budget.gemini_allowed(today=date(2027, 2, 10))
    world["rows"] = [("gemini", 1, 2.0, utc(2027, 2, 10))]
    assert not budget.gemini_allowed(today=date(2027, 2, 10))


def test_gemini_daily_cap_applies_inside_credit_period(world):
    world["rows"] = [("gemini", 1, 4.5, utc(2026, 11, 12))]
    budget.require("gemini", 0.5, now=NOW)
    with pytest.raises(budget.BudgetExceeded):
        budget.require("gemini", 0.6, now=NOW)


def test_gemini_require_blocked_after_credit(world):
    with pytest.raises(budget.BudgetExceeded):
        budget.require("gemini", 0.01, now=utc(2027, 2, 10))


def test_unknown_provider_passes(world):
    budget.require("groq", 1000, now=NOW)


def test_spent_since_pages_past_1000_rows(monkeypatch):
    monkeypatch.setattr(budget, "_cost_rows", REAL_COST_ROWS)
    data = [{"units": 1, "usd": 1.0, "created_at": "x"}] * 1500

    class Q:
        def __getattr__(self, _):
            return lambda *a, **k: self
        def range(self, lo, hi):
            self.lo, self.hi = lo, hi
            return self
        def execute(self):
            self.data = data[self.lo:min(self.hi + 1, 1000 + self.lo)]  # server caps a page at 1000
            return self

    class DB:
        def table(self, _):
            return Q()

    assert budget.spent_since(DB(), "gemini", NOW) == 1500
