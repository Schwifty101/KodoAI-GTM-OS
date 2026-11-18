from types import SimpleNamespace

import pytest

from gtm.budget import BudgetExceeded
from gtm.hunter import OutOfCredits
from gtm.sheet_verify import run_verify_sheet


class Q:
    def __init__(self, rows):
        self.rows, self.patch = rows, None
        self.not_ = SimpleNamespace(is_=self._not_null)

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) == v]
        return self

    def _not_null(self, k, _):
        self.rows = [r for r in self.rows if r.get(k) is not None]
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def execute(self):
        for r in self.rows:
            r.update(self.patch or {})
        return SimpleNamespace(data=self.rows)


class FakeDB:
    def __init__(self, leads):
        self.leads = leads

    def table(self, name):
        assert name == "leads"
        return Q(list(self.leads))


class Pool:
    def __init__(self, status="valid", score=90, raises=None):
        self.status, self.score, self.raises, self.calls = status, score, raises, []

    def verify_email(self, email, bucket):
        self.calls.append((email, bucket))
        if self.raises:
            raise self.raises
        return {"email": email, "verification_status": self.status, "score": self.score}


def lead(i="1", **kw):
    return {"id": i, "batch_id": "b", "status": "cleaned", "email_source": "sheet", "owner_email": "dana@spa.com", "email_verified": False,
            "owner_name": "Dana White", "owner_title": "Owner", **kw}


def test_valid_score_80_decision_maker_becomes_enriched():
    ls = [lead()]
    pool = Pool(score=80)
    assert run_verify_sheet(FakeDB(ls), pool, "b") == {"enriched": 1}
    assert ls[0]["status"] == "enriched" and ls[0]["email_verified"] is True and pool.calls == [("dana@spa.com", "hunter_import")]


def test_accept_all_and_webmail_fail_to_no_buyer():
    for status in ("accept_all", "webmail"):
        ls = [lead()]
        assert run_verify_sheet(FakeDB(ls), Pool(status=status), "b") == {"no_buyer": 1}
        assert ls[0]["status"] == "no_buyer" and ls[0]["email_verified"] is False


def test_role_address_info_at_fails():
    ls = [lead(owner_email="info@spa.com")]
    assert run_verify_sheet(FakeDB(ls), Pool(), "b") == {"no_buyer": 1} and ls[0]["status"] == "no_buyer"


def test_failed_lead_keeps_owner_name_and_title():
    ls = [lead()]
    run_verify_sheet(FakeDB(ls), Pool(score=50), "b")
    assert (ls[0]["owner_name"], ls[0]["owner_title"], ls[0]["owner_email"]) == ("Dana White", "Owner", "dana@spa.com")


def test_budget_exceeded_stops_and_leaves_lead_cleaned():
    for exc in (BudgetExceeded("cap"), OutOfCredits("none")):
        ls = [lead("1"), lead("2")]
        pool = Pool(raises=exc)
        assert run_verify_sheet(FakeDB(ls), pool, "b") == {"out_of_credits": 2}
        assert [r["status"] for r in ls] == ["cleaned", "cleaned"] and len(pool.calls) == 1


def test_lead_without_owner_or_decision_maker_title_stays_cleaned_and_is_skipped():
    for kw in ({"owner_title": "Practice Manager"}, {"owner_name": None}, {"owner_name": "  "}):
        ls = [lead(**kw)]
        pool = Pool()
        assert run_verify_sheet(FakeDB(ls), pool, "b") == {"skipped": 1} and not pool.calls
        assert ls[0]["status"] == "cleaned"


@pytest.fixture(autouse=True)
def _no_blocks(monkeypatch):
    monkeypatch.setattr("gtm.sheet_verify._blocklists", lambda db: (set(), set()), raising=False)


def test_blocked_leads_spend_nothing_and_become_suppressed(monkeypatch):
    monkeypatch.setattr("gtm.sheet_verify._blocklists", lambda db: ({"dana@spa.com", "bad.com"}, {"sent.com"}), raising=False)
    ls = [lead("1"), lead("2", owner_email="x@bad.com"), lead("3", owner_email="y@sent.com"), lead("4", owner_email="z@ok.com")]
    pool = Pool()
    assert run_verify_sheet(FakeDB(ls), pool, "b") == {"blocked": 3, "enriched": 1}
    assert [c[0] for c in pool.calls] == ["z@ok.com"] and [r["status"] for r in ls] == ["suppressed"] * 3 + ["enriched"]
    assert all(r["reject_reason"] == "sheet: already contacted or suppressed" for r in ls[:3])  # enrich does not check suppression


def test_limit_caps_leads_and_already_verified_are_skipped():
    ls = [lead("1"), lead("2"), lead("3", email_verified=True)]
    assert run_verify_sheet(FakeDB(ls), Pool(), "b", limit=1) == {"enriched": 1}
