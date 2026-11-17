import re
from datetime import datetime, timezone

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


@pytest.fixture(scope="session", autouse=True)
def _real_mailbox_untouched():
    """Guard: a test run must never pause, stamp or otherwise change the real mailbox row."""
    from gtm.db import get_db

    def row():
        try:
            return get_db().table("mailboxes").select("paused,paused_reason,replies_checked_at").eq("address", "soban@kodoai.xyz").execute().data
        except Exception:
            return None  # no database in this run: nothing to guard

    before = row()
    yield
    assert row() == before, "a test changed the real soban@kodoai.xyz mailbox row"


JUNK_BATCH = re.compile(r"^([A-Z] TX \d{4}-\d{2}-\d{2}|TEST.*|REHEARSAL_.*)$")


def is_junk_batch(row: dict, has_leads: bool, session_start: datetime) -> bool:
    """A batch a test run leaked: created this session, test-shaped name, no leads. Real batches never match."""
    return not has_leads and bool(JUNK_BATCH.match(row["name"])) and datetime.fromisoformat(row["created_at"]) >= session_start


@pytest.fixture(scope="session", autouse=True)
def _drop_leaked_test_batches():
    """Tests call new_batch and never delete it: sweep this session's empty test-named batches at teardown."""
    from gtm.db import get_db

    start = datetime.now(timezone.utc)  # ponytail: local vs DB clock skew only makes the sweep miss rows; name pattern + no leads still guard
    yield
    try:
        db = get_db()
        rows = db.table("batches").select("id,name,created_at").gte("created_at", start.isoformat()).execute().data
        used = {l["batch_id"] for l in db.table("leads").select("batch_id").in_("batch_id", [r["id"] for r in rows]).execute().data} if rows else set()
        junk = [r["id"] for r in rows if is_junk_batch(r, r["id"] in used, start)]
        if junk:
            db.table("batches").delete().in_("id", junk).execute()
    except Exception:
        pass  # no database in this run: nothing leaked
