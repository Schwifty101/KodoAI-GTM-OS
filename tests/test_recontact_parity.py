"""scripts/recontact_parity.py: the pure grouping parts, and the whole analysis against a fake db (no network, no real rows)."""
import sys
from datetime import date
from pathlib import Path

import pytest
from postgrest.exceptions import APIError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import recontact_parity as rp  # noqa: E402

from gtm import select as select_mod, settings_store  # noqa: E402
from test_select import TODAY, hist_row, os_lead, stack, sup_row, world  # noqa: E402  (pytest puts tests/ on sys.path; reuse the fake db)


class NoLedger:
    """The real database before migration 0018: the ledger table does not exist."""

    def __init__(self, db):
        self.db = db

    def table(self, name):
        if name == "contact_history":
            raise APIError({"code": "PGRST205", "message": "Could not find the table 'public.contact_history'"})
        return self.db.table(name)


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    settings_store.clear_cache()
    yield
    settings_store.clear_cache()


def test_released_by_reason_counts_each_key_once_per_reason():
    sup = [sup_row("a@x.com", reason="notion-contacted"), sup_row("a@x.com", "x.com", "sheet-sent"), sup_row(domain="x.com", reason="sheet-sent"),
           sup_row("a@x.com", reason="notion-contacted"), sup_row("z@z.com", reason="sheet-sent"), sup_row("q@q.com", reason=None)]
    assert rp.released_by_reason(sup, {"a@x.com", "x.com", "q@q.com"}) == {"notion-contacted": 1, "sheet-sent": 2, "(none)": 1}


def test_released_by_reason_is_empty_when_nothing_is_released():
    assert rp.released_by_reason([sup_row("a@x.com")], set()) == {}


def test_first_eligible_week_is_the_monday_of_last_sent_plus_days():
    assert rp.first_eligible_week("2026-11-18", 60) == date(2027, 1, 11)  # day 60 is Sunday 2027-01-17
    assert rp.first_eligible_week("2026-10-08T10:00:00+00:00", 60) == date(2026, 12, 7)  # a timestamp is cut to its date; day 60 is that Monday
    assert rp.first_eligible_week(None, 60) is None
    assert rp.first_eligible_week("not a date", 60) is None


def test_ledger_summary_counts_every_outcome_but_weeks_only_for_clear_ones():
    hist = [hist_row("a@a.com", None, "no_reply", last="2026-11-18"), hist_row("b@b.com", None, "auto_reply", last="2026-11-17"),
            hist_row("c@c.com", None, "replied", last="2026-11-18"), hist_row("d@d.com", None, "no_reply", last=None)]
    outcomes, weeks = rp.ledger_summary(hist, 60)
    assert outcomes == {"no_reply": 2, "auto_reply": 1, "replied": 1}
    assert weeks == {date(2027, 1, 11): 2, None: 1}  # the missing date is counted, not dropped


@pytest.mark.parametrize("code,missing", [("PGRST205", True), ("42P01", True), ("PGRST301", False), (None, False)])
def test_missing_table_is_recognised_by_code(code, missing):
    assert rp.is_missing_table(APIError({"code": code, "message": "x"})) is missing


def test_missing_table_ignores_other_exceptions():
    assert rp.is_missing_table(RuntimeError("contact_history unavailable")) is False


def test_analyse_before_the_migration_reports_parity_and_no_ledger():
    leads, touches = stack(os_lead(1, sent=(100,)))
    db = NoLedger(world(on=False, sup=[sup_row("a@glow.com", "glow.com")], leads=leads, touches=touches))
    res = rp.analyse(db, TODAY)
    assert res["ledger"] is False and res["real_flag"] is False
    assert (res["sup_before"], res["contacted_before"]) == (2, 2)
    assert rp.render(res)[-1] == "ledger table missing (migration 0018 not applied): released = 0"


def test_analyse_with_the_ledger_counts_released_keys_freed_contacts_and_weeks():
    sup = [sup_row("a@glow.com"), sup_row(domain="glow.com"), sup_row("g@auto.com", "auto.com", "sheet-sent"),
           sup_row("d@replied.com", "replied.com"), sup_row("b@bounce.com", "bounce.com", "bounce")]
    hist = [hist_row("a@glow.com", "glow.com", last=100), hist_row("g@auto.com", "auto.com", "auto_reply", 61), hist_row("d@replied.com", "replied.com", "replied", 200)]
    leads, touches = stack(os_lead(1, sent=(100,)), os_lead(2, sent=(10,)))  # the first is old enough, the second is not
    res = rp.analyse(world(on=True, sup=sup, hist=hist, leads=leads, touches=touches), TODAY)  # stored flag on: the script must still compare flag-off
    assert res["ledger"] is True and res["real_flag"] is True
    assert (res["sup_before"], res["sup_after"]) == (8, 4)
    assert res["released_by_reason"] == {"notion-contacted": 2, "sheet-sent": 2}
    assert (res["contacted_before"], res["contacted_after"], res["contacted_freed"]) == (4, 2, 2)
    assert res["outcomes"] == {"no_reply": 1, "auto_reply": 1, "replied": 1}
    assert res["weeks"] == {date(2026, 12, 21): 1, date(2027, 1, 25): 1}
    assert (res["days"], res["max_rounds"]) == (60, 3)
    text = "\n".join(rp.render(res))
    assert "released" in text and "notion-contacted: 2" in text and "a@glow.com" not in text  # counts only


def test_analyse_fails_when_flag_off_blocklists_differ_from_the_legacy_function(monkeypatch):
    monkeypatch.setattr(select_mod, "_blocklists", lambda db, today=None: ({"extra"}, set()))
    with pytest.raises(AssertionError, match="parity"):
        rp.analyse(NoLedger(world(on=False, sup=[sup_row("a@glow.com")])), TODAY)


def test_analyse_does_not_swallow_other_ledger_errors():
    with pytest.raises(RuntimeError, match="contact_history unavailable"):
        rp.analyse(world(on=True, boom=("contact_history",)), TODAY)  # flag on, ledger read fails for another reason: surface it
