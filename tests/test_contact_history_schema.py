import pytest
from postgrest.exceptions import APIError

from gtm.db import get_db

pytestmark = pytest.mark.db
db = get_db()

# SQLSTATE codes PostgREST passes through; PGRST205 and 42703 are what a missing table or column answers.
UNIQUE, CHECK = "23505", "23514"
MISSING = {"PGRST205", "42P01", "42703"}


@pytest.fixture(autouse=True)
def _migration_0018_applied():
    for q in (db.table("contact_history").select("id"), db.table("leads").select("round,history_id")):
        try:
            q.limit(1).execute()
        except APIError as e:
            if e.code in MISSING:
                pytest.skip("migration 0018 not applied")
            raise  # any other error is a real failure, never a skip


@pytest.fixture
def made():
    """Ids this test created; cleanup deletes only these (leads first, they point at the ledger)."""
    ids = {"leads": [], "contact_history": []}
    yield ids
    for table in ("leads", "contact_history"):
        if ids[table]:
            db.table(table).delete().in_("id", ids[table]).execute()


def ledger(made, **over) -> dict:
    row = {"email": "rc-test-1@example.invalid", "source": "notion", "source_ref": "TEST", "last_sent_on": "2026-09-01", "date_basis": "exact", "outcome": "no_reply"}
    row.update(over)
    made["contact_history"].append(db.table("contact_history").insert(row).execute().data[0]["id"])
    return row


def lead(made, place_id: str, **over) -> dict:
    # rejected, so the live autopilot never picks the row up; batch_no stays null
    row = {"place_id": place_id, "name": place_id, "status": "rejected", "reject_reason": "test"}
    row.update(over)
    got = db.table("leads").insert(row).execute().data[0]
    made["leads"].append(got["id"])
    return got


def code_of(fn) -> str:
    with pytest.raises(APIError) as e:
        fn()
    return e.value.code


def test_contact_history_unique_per_source_key_and_round(made):
    ledger(made)
    assert code_of(lambda: ledger(made)) == UNIQUE
    ledger(made, round=2)  # same contact, next round
    ledger(made, source="sheet")  # same contact, other source
    ledger(made, email=None, domain="rc-test-1.example.invalid")  # same source and round, other key


def test_contact_history_needs_an_email_or_a_domain(made):
    assert code_of(lambda: ledger(made, email=None)) == CHECK
    ledger(made, email=None, domain="rc-test-2.example.invalid")  # a domain alone is enough


def test_contact_history_rejects_an_unknown_outcome_or_date_basis(made):
    assert code_of(lambda: ledger(made, outcome="maybe")) == CHECK
    assert code_of(lambda: ledger(made, date_basis="guess")) == CHECK
    assert code_of(lambda: ledger(made, source="gmail")) == CHECK
    assert code_of(lambda: ledger(made, touches_sent=4)) == CHECK
    assert code_of(lambda: ledger(made, round=0)) == CHECK


def test_leads_round_defaults_to_one(made):
    assert lead(made, "TEST_rc_round")["round"] == 1


def test_leads_history_id_is_unique_when_set(made):
    ledger(made)
    hid = made["contact_history"][0]
    lead(made, "TEST_rc_hist_a", history_id=hid)
    assert code_of(lambda: lead(made, "TEST_rc_hist_b", history_id=hid)) == UNIQUE
    lead(made, "TEST_rc_hist_c")  # null history_id may repeat
    lead(made, "TEST_rc_hist_d")
