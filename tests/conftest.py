import pytest

from gtm.settings_store import DEFAULTS


@pytest.fixture(autouse=True)
def _no_budget_db(monkeypatch):
    """Unit tests of paid calls never read the real database through the budget gate."""
    monkeypatch.setattr("gtm.budget._cost_rows", lambda db, provider, since: [])
    monkeypatch.setattr("gtm.budget.setting", lambda key, db=None: DEFAULTS[key])


def real_jobs(db) -> list[dict]:
    """Queued or running jobs that are not test rows."""
    return db.table("jobs").select("id").in_("status", ["queued", "running"]).or_("payload->>test.is.null,payload->>test.neq.1").execute().data


@pytest.fixture
def no_real_jobs():
    """Claim tests must never claim, finish or requeue real work: skip when any exists."""
    from gtm.db import get_db

    if real_jobs(get_db()):
        pytest.skip("real jobs in the queue: refusing to run claim tests against them")
