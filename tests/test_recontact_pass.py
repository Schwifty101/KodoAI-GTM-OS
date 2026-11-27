"""Plan 9 Task 6: the recontact pass. Fake db and real HunterPool over a fake http: no network, no real rows, synthetic @example.test data."""
from __future__ import annotations

import copy
import itertools
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from gtm.budget import BudgetExceeded
from gtm.hunter import HunterPool
from gtm.recontact_pass import candidates, run_recontact
from gtm.settings_store import DEFAULTS

TODAY = date(2027, 3, 1)


def ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


class Q:
    """Supabase-style chained query over a list of dicts. Projects the selected columns; unknown tables raise."""

    def __init__(self, db, name):
        self.db, self.name, self.filters, self.cols, self.span, self.cap, self.payload = db, name, [], "*", None, None, None

    def select(self, cols="*"):
        self.cols = cols
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.filters.append(lambda r: r.get(col) in vals)
        return self

    def order(self, col):
        return self

    def limit(self, n):
        self.cap = n
        return self

    def range(self, lo, hi):
        self.span = (lo, hi)
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        db = self.db
        rows = db.tables[self.name]  # KeyError for a table the pass has no business touching
        if self.payload is not None:
            out = []
            for r in self.payload if isinstance(self.payload, list) else [self.payload]:
                row = {"id": f"{self.name[:2]}{next(db.seq)}", **r}
                for col in db.unique.get(self.name, ()):
                    assert row.get(col) is None or all(x.get(col) != row[col] for x in rows), f"duplicate {self.name}.{col}"
                rows.append(row)
                db.writes.append((self.name, "insert"))
                out.append(dict(row))
            return SimpleNamespace(data=out)
        hit = [r for r in rows if all(f(r) for f in self.filters)]
        if self.span:
            hit = hit[self.span[0] : self.span[1] + 1]
        if self.cap:
            hit = hit[: self.cap]
        cols = None if self.cols == "*" else self.cols.split(",")
        return SimpleNamespace(data=[{c: r.get(c) for c in cols} if cols else dict(r) for r in hit])


class DB:
    unique = {"leads": ("place_id", "history_id")}

    def __init__(self, hist=(), leads=(), touches=(), sup=()):
        self.tables = {"contact_history": list(hist), "leads": list(leads), "touches": list(touches), "suppression": list(sup), "batches": []}
        self.writes, self.seq = [], itertools.count(1)

    def table(self, name):
        return Q(self, name)

    @property
    def new_leads(self):
        return [r for r in self.tables["leads"] if r.get("history_id") and r["id"].startswith("le")]


def hist(i, last=100, **kw):
    return {"id": f"H{i}", "email": f"owner{i}@clinic{i}.example.test", "domain": f"clinic{i}.example.test", "business_name": f"Clinic {i} Med Spa",
            "owner_name": "Dana Example", "owner_title": "Owner", "website": f"https://clinic{i}.example.test", "city": "Austin", "state": "TX",
            "round": 1, "outcome": "no_reply", "date_basis": "exact", "first_sent_on": ago(last + 7), "last_sent_on": ago(last), "touches_sent": 3,
            "source": "notion", "lead_id": None, **kw}


def os_lead(i, status="sent", sent=(100, 97, 93), place_id=None, rnd=1, **kw):
    """(lead, touches) for an OS-mailed lead; sent = days ago."""
    lead = {"id": f"L{i}", "place_id": place_id or f"ChIJ{i}", "status": status, "name": f"Os Clinic {i}", "website": f"https://os{i}.example.test",
            "domain": f"os{i}.example.test", "city": "Dallas", "state": "TX", "owner_name": "Sam Example", "owner_title": "Founder",
            "owner_email": f"sam{i}@os{i}.example.test", "round": rnd, "history_id": None, **kw}
    return lead, [{"lead_id": f"L{i}", "status": "sent", "sent_at": ago(n) + "T15:00:00+00:00"} for n in sent]


def world(hist_rows=(), pairs=(), sup=(), extra_leads=(), extra_touches=()):
    return DB(hist_rows, [l for l, _ in pairs] + list(extra_leads), [t for _, ts in pairs for t in ts] + list(extra_touches), sup)


@pytest.fixture
def env(monkeypatch):
    """Settings and the Hunter cost log are plain dicts and lists: budget.require sees them, the real database is never read."""
    S = {"recontact_on": True, "recontact_hunter_allowance_credits": 10.0}
    costs: list[dict] = []
    get = lambda key, db=None: S.get(key, DEFAULTS[key])
    monkeypatch.setattr("gtm.budget.setting", get)
    monkeypatch.setattr("gtm.recontact_pass.setting", get)
    monkeypatch.setattr("gtm.budget._cost_rows", lambda db, provider, since: [{"units": c["units"], "usd": c["usd"]} for c in costs if c["provider"] == provider])
    return SimpleNamespace(S=S, costs=costs)


def pool(env, status="valid", score=90):
    calls: list[str] = []

    def http(path, params, key):
        calls.append(params["email"])
        return 200, {"data": {"status": status, "score": score}}

    p = HunterPool(["k"], http=http, sleep=lambda s: None,
                   log=lambda units, note, bucket="hunter": env.costs.append({"provider": bucket, "units": units, "usd": None, "note": note}))
    p.calls = calls
    return p


def run(env, db, p=None, limit=5, confirm=True):
    return run_recontact(db, p or pool(env), limit, confirm, TODAY)


def ids(cands):
    return [c.get("id") or c["lead_id"] for c in cands]


def test_eligible_pre_os_contact_becomes_an_enriched_lead_when_hunter_says_valid(env):
    db, p = world([hist(1)]), pool(env)
    assert run(env, db, p) == {"candidates": 1, "enriched": 1}
    [batch] = db.tables["batches"]
    [lead] = db.new_leads
    assert batch["name"] == "Recontact 2027-03-01"
    assert lead | {"id": None} == {
        "id": None, "place_id": "recontact:H1", "name": "Clinic 1 Med Spa", "website": "https://clinic1.example.test", "domain": "clinic1.example.test",
        "city": "Austin", "state": "TX", "tz": "America/Chicago", "owner_name": "Dana Example", "owner_title": "Owner",
        "owner_email": "owner1@clinic1.example.test", "email_source": "history", "email_verified": True, "status": "enriched", "round": 2,
        "history_id": "H1", "batch_id": batch["id"]}
    assert p.calls == ["owner1@clinic1.example.test"]


@pytest.mark.parametrize("status,score", [("invalid", 95), ("valid", 74), ("accept_all", 99), ("unknown", 0)])
def test_failed_verification_saves_a_no_buyer_lead_and_keeps_the_name(env, status, score):
    db = world([hist(1)])
    assert run(env, db, pool(env, status, score)) == {"candidates": 1, "no_buyer": 1}
    [lead] = db.new_leads
    assert (lead["status"], lead["owner_name"], lead["owner_title"], lead["email_verified"]) == ("no_buyer", "Dana Example", "Owner", False)
    assert len(env.costs) == 1  # a failed verification still spent its credit


@pytest.mark.parametrize("name,title", [("Dana Example", "Office Manager"), ("Dana Example", None), ("Dana Example", "Franchise Owner"), ("", "Owner"), (None, "Owner")])
def test_non_decision_maker_title_spends_nothing_and_is_skipped(env, name, title):
    db, p = world([hist(1, owner_name=name, owner_title=title)]), pool(env)
    assert run(env, db, p) == {"candidates": 1, "not_decision_maker": 1}
    assert p.calls == [] and env.costs == [] and db.new_leads == [] and db.writes == []


def test_dry_run_creates_nothing_spends_nothing_and_prints_cost_and_allowance(env, capsys):
    env.S["recontact_on"] = False  # a dry run is a preview: it needs neither the flag nor a pool
    pairs = [os_lead(7)]
    db = world([hist(1), hist(2), hist(3, owner_title="Office Manager")], pairs)
    assert run_recontact(db, None, None, False, TODAY) == {"candidates": 4, "eligible": 3, "not_decision_maker": 1}
    out = capsys.readouterr().out
    assert "0.5 x 3" in out and "allowance left 10.0" in out and "not_decision_maker" in out
    assert db.writes == [] and env.costs == [] and db.tables["batches"] == []
    run_recontact(db, None, 2, False, TODAY)
    assert "0.5 x 2" in capsys.readouterr().out  # the limit caps the estimate


def test_apply_refuses_with_recontact_off(env):
    env.S["recontact_on"] = False
    db, p = world([hist(1)]), pool(env)
    with pytest.raises(ValueError, match="recontact_on"):
        run(env, db, p)
    assert p.calls == [] and db.writes == []


@pytest.mark.parametrize("limit", [None, 0, -3, True])
def test_apply_refuses_without_limit(env, limit):
    db = world([hist(1)])
    p = pool(env)
    with pytest.raises(ValueError, match="limit"):
        run(env, db, p, limit=limit)
    assert p.calls == [] and db.writes == []


@pytest.mark.parametrize("allowance,spent", [(0.0, 0), (1.0, 0.75), (2.0, 2.0)])
def test_apply_with_zero_allowance_raises_before_any_paid_call(env, allowance, spent):
    env.S["recontact_hunter_allowance_credits"] = allowance
    if spent:
        env.costs.append({"provider": "hunter_recontact", "units": spent, "usd": None})
    db = world([hist(1)])
    p = pool(env)
    with pytest.raises(BudgetExceeded) as e:
        run(env, db, p)
    assert e.value.kind == "credit" and p.calls == [] and db.writes == [] and len(env.costs) == (1 if spent else 0)


def test_second_run_creates_no_duplicate_lead(env):
    db = world([hist(1)])
    p = pool(env)
    assert run(env, db, p) == {"candidates": 1, "enriched": 1}
    assert run(env, db, p) == {"candidates": 0}  # the fake db also rejects a second lead with the same history_id or place_id
    assert len(db.new_leads) == 1 and len(p.calls) == 1 and len(db.tables["batches"]) == 1


def test_os_sent_lead_gets_a_ledger_snapshot_and_a_round_two_lead_and_the_old_rows_are_untouched(env):
    pair = os_lead(1)
    db = world(pairs=[pair])
    before = copy.deepcopy((db.tables["leads"], db.tables["touches"]))
    assert ids(candidates(db, TODAY)) == ["L1"]
    assert run(env, db) == {"candidates": 1, "enriched": 1}
    [snap] = db.tables["contact_history"]
    assert snap | {"id": None} == {
        "id": None, "source": "os", "email": "sam1@os1.example.test", "domain": "os1.example.test", "business_name": "Os Clinic 1", "owner_name": "Sam Example",
        "owner_title": "Founder", "website": "https://os1.example.test", "city": "Dallas", "state": "TX", "round": 1, "outcome": "no_reply",
        "date_basis": "exact", "first_sent_on": ago(100), "last_sent_on": ago(93), "touches_sent": 3, "lead_id": "L1"}
    [lead] = db.new_leads
    assert (lead["round"], lead["history_id"], lead["place_id"], lead["status"]) == (2, snap["id"], f"recontact:{snap['id']}", "enriched")
    assert db.writes == [("batches", "insert"), ("contact_history", "insert"), ("leads", "insert")]  # the snapshot goes in before the new lead
    assert (db.tables["leads"][0], db.tables["touches"]) == (before[0][0], before[1])  # old lead and touches are never edited
    assert candidates(db, TODAY) == []  # the snapshot now has a lead, the old lead a snapshot


@pytest.mark.parametrize("open_status", ["drafted", "held", "edited", "approved", "scheduled", "sending"])
def test_open_sequence_is_not_a_candidate(env, open_status):
    lead, touches = os_lead(1, sent=(100,))
    touches.append({"lead_id": "L1", "status": open_status, "sent_at": None})
    assert candidates(world(pairs=[(lead, touches)]), TODAY) == []


@pytest.mark.parametrize("status", ["replied", "booked", "bounced", "unsubscribed", "suppressed", "drafted", "selected", "enriched"])
def test_replied_bounced_unsubscribed_and_suppressed_leads_are_never_candidates(env, status):
    assert candidates(world(pairs=[os_lead(1, status=status)]), TODAY) == []


def test_os_lead_with_a_permanent_suppression_row_on_its_domain_is_not_a_candidate(env):
    sup = [{"email": None, "domain": "os1.example.test", "reason": "do-not-contact"}]
    assert candidates(world(pairs=[os_lead(1)], sup=sup), TODAY) == []
    cooldown = [{"email": None, "domain": "os1.example.test", "reason": "notion-contacted"}]
    assert ids(candidates(world(pairs=[os_lead(1)], sup=cooldown), TODAY)) == ["L1"]


def test_snapshot_row_of_a_lead_that_later_replied_is_not_a_candidate(env):
    lead, touches = os_lead(1, status="replied")
    snap = hist(9, source="os", lead_id="L1", email="sam1@os1.example.test", domain="os1.example.test")
    assert candidates(world([snap], [(lead, touches)]), TODAY) == []


def test_test_and_rehearsal_leads_are_never_candidates(env):
    pairs = [os_lead(1, place_id="TEST_1"), os_lead(2, place_id="REHEARSAL_2"), os_lead(3)]
    assert ids(candidates(world(pairs=pairs), TODAY)) == ["L3"]


@pytest.mark.parametrize("status", ["cleaned", "enriched", "signalled", "selected", "drafted", "sent", "replied", "booked", "bounced", "unsubscribed"])
def test_live_twin_lead_is_skipped_and_counted(env, status):
    twin = {"id": "T1", "place_id": "ChIJtwin", "status": status, "domain": "clinic1.example.test", "owner_email": None, "round": 1, "history_id": None}
    twin_touches = [{"lead_id": "T1", "status": "sent", "sent_at": ago(10) + "T15:00:00+00:00"}] if status == "sent" else []
    db, p = world([hist(1)], extra_leads=[twin], extra_touches=twin_touches), pool(env)
    assert run(env, db, p) == {"candidates": 1, "live_twin": 1}
    assert p.calls == [] and db.new_leads == []


@pytest.mark.parametrize("status", ["scraped", "rejected", "no_buyer", "suppressed"])
def test_a_twin_that_is_not_live_does_not_block(env, status):
    twin = {"id": "T1", "place_id": "ChIJtwin", "status": status, "domain": "clinic1.example.test", "owner_email": "owner1@clinic1.example.test", "round": 1, "history_id": None}
    assert run(env, world([hist(1)], extra_leads=[twin])) == {"candidates": 1, "enriched": 1}


def test_a_twin_with_the_same_email_in_another_case_and_domain_is_caught_and_new_leads_count_as_twins(env):
    twin = {"id": "T1", "place_id": "ChIJtwin", "status": "cleaned", "domain": "other.example.test", "owner_email": "Owner1@Clinic1.Example.Test", "round": 1, "history_id": None}
    assert run(env, world([hist(1)], extra_leads=[twin])) == {"candidates": 1, "live_twin": 1}
    # two ledger rows of one company: the first becomes an enriched lead, the second then has a live twin
    two = [hist(1, last=120), hist(2, last=100, domain="clinic1.example.test", email="second@elsewhere.example.test")]
    assert run(env, world(two)) == {"candidates": 2, "enriched": 1, "live_twin": 1}


def test_previous_round_of_the_same_contact_is_not_a_twin(env):
    first, first_touches = os_lead(1, sent=(200, 197, 193))  # round 1, long past its cooldown, already re-entered
    second, second_touches = os_lead(1, sent=(100,), rnd=2, history_id="H1", id="L2", place_id="ChIJ2")
    second_touches = [{**t, "lead_id": "L2"} for t in second_touches]
    snap = hist(1, source="os", lead_id="L1", email=first["owner_email"], domain=first["domain"], last=193)
    db = world([snap], [(first, first_touches), (second, second_touches)])
    assert ids(candidates(db, TODAY)) == ["L2"]
    assert run(env, db) == {"candidates": 1, "enriched": 1}
    [new] = db.new_leads
    assert new["round"] == 3 and new["history_id"] not in ("H1", None)


def test_non_us_day_spa_and_no_domain_contacts_are_skipped(env):
    rows = [
        hist(1, state="Ontario"),
        hist(2, business_name="Serenity Day Spa"),
        hist(3, business_name="Glow Beauty Academy"),
        hist(4, domain=None, website=None),
        hist(5, domain="instagram.com", website=None),
        hist(6, email=None),
        hist(7, domain=None, website="https://www.derived.example.test/book"),  # eligible: the domain comes from the website
    ]
    db = world(rows)
    p = pool(env)
    assert run(env, db, p) == {"candidates": 7, "not_us": 1, "day_spa": 1, "school": 1, "no_domain": 2, "no_email": 1, "enriched": 1}
    assert [l["domain"] for l in db.new_leads] == ["derived.example.test"] and len(p.calls) == 1


@pytest.mark.parametrize("status,score,email", [("valid", 90, None), ("invalid", 90, None), ("accept_all", 99, None), ("valid", 80, "info@clinic1.example.test")])
def test_new_lead_is_never_created_cleaned(env, status, score, email):
    db = world([hist(1, **({"email": email} if email else {}))])
    p = pool(env, status, score)
    run(env, db, p)
    assert [l["status"] for l in db.new_leads] in (["enriched"], ["no_buyer"])
    if email:  # a role address never qualifies and is not kept as the owner's email; it cost nothing to find out
        assert db.new_leads[0]["owner_email"] is None and p.calls == []


def test_cost_rows_use_the_hunter_recontact_bucket(env):
    run(env, world([hist(1), hist(2)]))
    assert [(c["provider"], c["units"]) for c in env.costs] == [("hunter_recontact", 0.5)] * 2


@pytest.mark.parametrize("rnd,expected", [(3, []), (2, ["L1"])])
def test_lead_at_max_rounds_is_not_a_candidate(env, rnd, expected):
    assert ids(candidates(world(pairs=[os_lead(1, rnd=rnd)]), TODAY)) == expected
    assert ids(candidates(world([hist(1, round=rnd)]), TODAY)) == (["H1"] if expected else [])


def test_candidates_are_oldest_last_send_first(env):
    db = world([hist(1, last=70), hist(2, last=200), hist(3, last=90)], [os_lead(4, sent=(130, 120))])
    assert ids(candidates(db, TODAY)) == ["H2", "L4", "H3", "H1"]
    p = pool(env)
    run(env, db, p)
    assert p.calls == ["owner2@clinic2.example.test", "sam4@os4.example.test", "owner3@clinic3.example.test", "owner1@clinic1.example.test"]


def test_limit_counts_created_leads_so_skipped_candidates_never_clog_the_front(env):
    rows = [hist(1, last=300, owner_title="Office Manager"), hist(2, last=290, owner_title="Office Manager"), hist(3, last=200), hist(4, last=100)]
    db = world(rows)
    assert run(env, db, limit=1) == {"candidates": 4, "not_decision_maker": 2, "enriched": 1}
    assert [l["history_id"] for l in db.new_leads] == ["H3"]  # H4 is left for the next run


def test_out_of_credits_stops_the_run_and_leaves_the_rest_untouched(env):
    env.S["recontact_hunter_allowance_credits"] = 1.0  # two verifications
    pairs = [os_lead(9, sent=(150,))]  # the third, oldest-last: an OS lead that must get no snapshot row
    db = world([hist(1, last=300), hist(2, last=200)], pairs)
    assert run(env, db, limit=5) == {"candidates": 3, "enriched": 2, "out_of_credits": 1}
    assert [l["history_id"] for l in db.new_leads] == ["H1", "H2"] and len(env.costs) == 2
    assert [r["id"] for r in db.tables["contact_history"]] == ["H1", "H2"]  # no snapshot for the unreached OS lead
    assert sorted(l["place_id"] for l in db.tables["leads"]) == ["ChIJ9", "recontact:H1", "recontact:H2"]
