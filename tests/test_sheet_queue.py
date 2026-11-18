import itertools
from types import SimpleNamespace

import pytest

from gtm import sheet_queue
from gtm.budget import BudgetExceeded
from gtm.sheet import QUEUE_HEADER, SheetRow
from gtm.sheet_queue import pull_sheet_only, queue_order, run_queue, select_queue

_ids = itertools.count(1)
IN_SIZES: list[int] = []


class Q:
    """Just enough of the supabase query builder, over in-memory rows."""

    def __init__(self, tables, name):
        self.tables, self.name, self.rows, self.patch, self.mode = tables, name, list(tables[name]), None, "select"
        self.not_ = SimpleNamespace(is_=self._not_is)
        self.lo = self.hi = None

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) == v]
        return self

    def neq(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) != v]
        return self

    def in_(self, k, vs):
        IN_SIZES.append(len(vs))
        self.rows = [r for r in self.rows if r.get(k) in vs]
        return self

    def like(self, k, pat):
        self.rows = [r for r in self.rows if str(r.get(k)).startswith(pat.rstrip("%"))]
        return self

    def is_(self, k, _):
        self.rows = [r for r in self.rows if r.get(k) is None]
        return self

    def _not_is(self, k, _):
        self.rows = [r for r in self.rows if r.get(k) is not None]
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def range(self, lo, hi):
        self.rows = self.rows[lo:hi + 1]
        return self

    def update(self, patch):
        self.mode, self.patch = "update", patch
        return self

    def insert(self, rows):
        self.mode, self.patch = "insert", rows if isinstance(rows, list) else [rows]
        return self

    def upsert(self, rows, **k):  # on_conflict ignore: skip rows whose conflict key already exists
        rows = rows if isinstance(rows, list) else [rows]
        keys = k.get("on_conflict", "").split(",")
        have = {tuple(r.get(c) for c in keys) for r in self.tables[self.name]}
        return self.insert([r for r in rows if tuple(r.get(c) for c in keys) not in have])

    def execute(self):
        if self.mode == "update":
            if self.name == "leads" and self.tables.get("fail_lead_update") and self.patch.get("status") == "no_buyer":
                raise RuntimeError("lead update failed")
            for r in self.rows:
                r.update(self.patch)
        elif self.mode == "insert":
            if self.name == "sheet_rows" and self.tables.get("fail_sheet_rows"):
                raise RuntimeError("sheet_rows write failed")
            self.rows = [{"id": f"id{next(_ids)}", **r} for r in self.patch]
            self.tables[self.name].extend(self.rows)
        return SimpleNamespace(data=self.rows)


class FakeDB:
    def __init__(self, leads=(), sheet_rows=(), suppression=(), touches=()):
        self.tables = {"fail_sheet_rows": False, "fail_lead_update": False, "leads": list(leads), "sheet_rows": list(sheet_rows), "suppression": list(suppression), "touches": list(touches), "batches": []}

    def table(self, name):
        return Q(self.tables, name)


def L(i, **kw):
    return {"id": i, "name": f"Biz {i}", "domain": f"{i}.com", "status": "no_buyer", "owner_name": f"Own {i}", "owner_title": "Owner",
            "owner_email": None, "owner_linkedin": None, "review_count": None, "rating": None, **kw}


# ---- Task 8: ordering and selection (pure) ----

def test_order_named_then_linkedin_then_reviews_then_rating():
    leads = [L("unnamed", owner_name=None, review_count=900, owner_linkedin="x"),
             L("rating_low", review_count=50, rating=4.0),
             L("rating_high", review_count=50, rating=4.9),
             L("reviews", review_count=200),
             L("linkedin", owner_linkedin="https://li/x", review_count=1)]
    assert [x["id"] for x in queue_order(leads)] == ["linkedin", "reviews", "rating_high", "rating_low", "unnamed"]


def test_sheet_only_rows_sort_after_rows_with_reviews():
    leads = [L("sheet_only"), L("db", review_count=3, rating=3.0)]
    assert [x["id"] for x in queue_order(leads)] == ["db", "sheet_only"]


def test_failed_lead_is_never_requeued():
    db = FakeDB([L("a"), L("b")], [{"lead_id": "a", "queue_state": "failed"}])
    assert [x["id"] for x in select_queue(db, 5)] == ["b"]


def test_waiting_lead_is_not_selected_twice():
    db = FakeDB([L("a"), L("b")], [{"lead_id": "a", "queue_state": "waiting"}, {"lead_id": "b", "queue_state": "verified"}])
    assert select_queue(db, 5) == []


def test_suppressed_lead_is_not_selected():
    db = FakeDB([L("a", domain="bad.com"), L("b")], suppression=[{"email": None, "domain": "bad.com"}])
    assert [x["id"] for x in select_queue(db, 5)] == ["b"]


def test_select_takes_only_no_buyer_named_without_email_and_n():
    db = FakeDB([L("a", status="enriched"), L("b", owner_email="x@y.com"), L("c", owner_name=None), L("d", review_count=9), L("e", review_count=5), L("f")])
    assert [x["id"] for x in select_queue(db, 2)] == ["d", "e"]


def test_pull_sheet_only_inserts_scraped_then_cleans_then_no_buyer(monkeypatch):
    def m(name, cat, **f):
        return SimpleNamespace(tab="Texas", block=1, row_no=5, colour=None, emails=[],
                               fields={"name": name, "website": f"https://www.{name.lower()}.com", "category": cat, "owner_name": "Dana White",
                                       "owner_title": "Owner", "owner_linkedin": "https://li/d", "state": "TX", "city": "Austin", **f},
                               ), f"domain:{name.lower()}.com"

    rows = [m("Glowmed", "Medical spa"), m("Dentist", "Dentist"), m("Nameless", "Medical spa", owner_name="")]
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: rows)
    db = FakeDB()
    assert pull_sheet_only(db, object(), "sid") == 1
    by_name = {r["name"]: r for r in db.tables["leads"]}
    assert set(by_name) == {"Glowmed", "Dentist"}
    assert by_name["Glowmed"]["status"] == "no_buyer" and by_name["Glowmed"]["owner_name"] == "Dana White" and by_name["Glowmed"]["owner_linkedin"] == "https://li/d"
    assert by_name["Dentist"]["status"] == "rejected"
    assert [(r["tab"], r["row_key"], r["lead_id"]) for r in db.tables["sheet_rows"]] == [("Texas", "domain:glowmed.com", by_name["Glowmed"]["id"])]
    assert pull_sheet_only(db, object(), "sid") == 0  # a second pull finds them already known


def _sheet_row(name, key):
    return SimpleNamespace(tab="Texas", block=1, row_no=5, colour=None, emails=[],
                           fields={"name": name, "website": f"https://www.{name.lower()}.com", "category": "Medical spa", "owner_name": "Dana White",
                                   "owner_title": "Owner", "state": "TX", "city": "Austin"}), key


def test_pull_sheet_only_never_sends_more_than_100_keys_in_one_query(monkeypatch):
    rows = [_sheet_row(f"Spa{i}", f"domain:spa{i}.com") for i in range(250)]
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: rows)
    IN_SIZES.clear()
    assert pull_sheet_only(FakeDB(), object(), "sid") == 250
    assert max(IN_SIZES) <= 100


def test_failed_sheet_rows_write_leaves_lead_cleaned_and_next_pull_retries(monkeypatch):
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: [_sheet_row("Glowmed", "domain:glowmed.com")])
    db = FakeDB()
    db.tables["fail_sheet_rows"] = True
    with pytest.raises(RuntimeError):
        pull_sheet_only(db, object(), "sid")
    assert [r["status"] for r in db.tables["leads"]] == ["cleaned"]
    db.tables["fail_sheet_rows"] = False
    assert pull_sheet_only(db, object(), "sid") == 1
    assert [r["status"] for r in db.tables["leads"]] == ["no_buyer"] and len(db.tables["leads"]) == 1 and len(db.tables["sheet_rows"]) == 1


def test_crash_after_sheet_rows_upsert_before_lead_flip_is_retried(monkeypatch):
    monkeypatch.setattr(sheet_queue, "_mapped", lambda svc, sheet_id: [_sheet_row("Glowmed", "domain:glowmed.com")])
    db = FakeDB()
    db.tables["fail_lead_update"] = True
    with pytest.raises(RuntimeError):
        pull_sheet_only(db, object(), "sid")
    assert [r["status"] for r in db.tables["leads"]] == ["cleaned"] and len(db.tables["sheet_rows"]) == 1
    db.tables["fail_lead_update"] = False
    assert pull_sheet_only(db, object(), "sid") == 1
    assert [r["status"] for r in db.tables["leads"]] == ["no_buyer"] and len(db.tables["sheet_rows"]) == 1


# ---- Task 9: queue tab run ----

class Pool:
    def __init__(self, verdicts=None, raises=None):
        self.verdicts, self.raises, self.calls = verdicts or {}, raises, []

    def verify_email(self, email, bucket):
        self.calls.append((email, bucket))
        if self.raises:
            raise self.raises
        status, score = self.verdicts.get(email, ("valid", 90))
        return {"email": email, "verification_status": status, "score": score}


class Svc:
    """Fake Sheets client: serves a Queue tab to read_tab and records write_queue_tab calls."""

    def __init__(self, rows):
        self.rows, self.written = rows, None


@pytest.fixture
def sheet(monkeypatch):
    def install(tab_rows):
        svc = Svc(tab_rows)
        monkeypatch.setattr(sheet_queue, "read_tab", lambda s, sid, tab: [SheetRow(tab, i + 1, c, [None] * len(c)) for i, c in enumerate(s.rows)])
        monkeypatch.setattr(sheet_queue, "write_queue_tab", lambda s, sid, rows: setattr(s, "written", rows))
        return svc
    return install


def tab(*rows):
    return [QUEUE_HEADER, *rows]


def trow(lead_id, email="", status="waiting"):
    return [f"Biz {lead_id}", f"Own {lead_id}", f"{lead_id}.com", "https://x", email, status, lead_id]


def waiting(db, *ids):
    db.tables["sheet_rows"] += [{"id": f"sr{i}", "tab": "Queue", "block": 0, "row_key": i, "lead_id": i, "queue_state": "waiting"} for i in ids]


def state(db, i):
    return next(r["queue_state"] for r in db.tables["sheet_rows"] if r["lead_id"] == i)


def test_valid_pasted_email_enriches_the_lead_and_removes_the_row(sheet):
    db = FakeDB([L("a")])
    waiting(db, "a")
    svc, pool = sheet(tab(trow("a", "dana@spa.com"))), Pool()
    out = run_queue(db, svc, pool, "sid", 0, confirm=True)
    lead = db.tables["leads"][0]
    assert (lead["status"], lead["email_verified"], lead["owner_email"], lead["email_source"]) == ("enriched", True, "dana@spa.com", "contactout")
    assert state(db, "a") == "verified" and svc.written == [] and out["enriched"] == 1
    assert pool.calls == [("dana@spa.com", "hunter")]  # the daily bucket, not the import allowance


def test_failed_pasted_email_leaves_no_buyer_and_marks_failed(sheet):
    db = FakeDB([L("a")])
    waiting(db, "a")
    svc = sheet(tab(trow("a", "dana@spa.com")))
    out = run_queue(db, svc, Pool({"dana@spa.com": ("accept_all", 99)}), "sid", 0, confirm=True)
    lead = db.tables["leads"][0]
    assert lead["status"] == "no_buyer" and lead["owner_email"] is None and state(db, "a") == "failed" and out["failed"] == 1 and svc.written == []


def test_paste_for_a_non_waiting_lead_is_ignored_and_listed(sheet, capsys):
    db = FakeDB([L("a", status="enriched"), L("b")])
    db.tables["sheet_rows"].append({"id": "x", "tab": "Queue", "block": 0, "row_key": "a", "lead_id": "a", "queue_state": "verified"})
    svc, pool = sheet(tab(trow("a", "dana@spa.com", "waiting"))), Pool()
    out = run_queue(db, svc, pool, "sid", 1, confirm=True)
    assert out["ignored"] == 1 and not pool.calls and db.tables["leads"][0]["owner_email"] is None
    assert "a" in capsys.readouterr().out  # listed
    assert [r[6] for r in svc.written] == ["b"]  # and the stale row is gone


def test_tab_is_topped_up_to_size_without_duplicates(sheet):
    db = FakeDB([L(i, review_count=int(n)) for i, n in zip("abcdef", "654321")])
    waiting(db, "a")
    svc = sheet(tab(trow("a")))
    out = run_queue(db, svc, Pool(), "sid", 3, confirm=True)
    assert [r[6] for r in svc.written] == ["a", "b", "c"] and out["added"] == 2 and out["waiting"] == 3
    assert {r[5] for r in svc.written} == {"waiting"} and state(db, "b") == "waiting"
    assert svc.written[1][3] == "https://www.linkedin.com/search/results/people/?keywords=Own+b+Biz+b"
    out = run_queue(db, sheet(tab(*svc.written)), Pool(), "sid", 3, confirm=True)  # a rerun adds nothing
    assert out["added"] == 0


def test_sorted_tab_still_matches_by_lead_id(sheet):
    db = FakeDB([L("a"), L("b")])
    waiting(db, "a", "b")
    svc = sheet(tab(trow("b", "bob@spa.com"), trow("a", "ann@spa.com")))
    run_queue(db, svc, Pool({"bob@spa.com": ("invalid", 10)}), "sid", 0, confirm=True)
    assert state(db, "b") == "failed" and state(db, "a") == "verified"
    assert next(x for x in db.tables["leads"] if x["id"] == "a")["owner_email"] == "ann@spa.com"


def test_dry_run_writes_and_spends_nothing(sheet, capsys):
    db = FakeDB([L("a"), L("b")])
    waiting(db, "a")
    svc, pool = sheet(tab(trow("a", "dana@spa.com"))), Pool()
    run_queue(db, svc, pool, "sid", 3)
    assert svc.written is None and not pool.calls and db.tables["leads"][0]["status"] == "no_buyer" and state(db, "a") == "waiting"
    assert len(db.tables["sheet_rows"]) == 1 and "credits" in capsys.readouterr().out


def test_budget_exceeded_keeps_row_waiting(sheet):
    db = FakeDB([L("a"), L("b")])
    waiting(db, "a", "b")
    svc = sheet(tab(trow("a", "ann@spa.com"), trow("b", "bob@spa.com")))
    out = run_queue(db, svc, Pool(raises=BudgetExceeded("cap")), "sid", 2, confirm=True)
    assert state(db, "a") == "waiting" and out["out_of_credits"] == 2
    assert [(r[6], r[4]) for r in svc.written] == [("a", "ann@spa.com"), ("b", "bob@spa.com")]  # typed emails survive for tomorrow


def test_pasted_email_is_trimmed_and_lowercased_before_verify(sheet):
    db = FakeDB([L("a")])
    waiting(db, "a")
    pool = Pool()
    run_queue(db, sheet(tab(trow("a", "  Dana@Spa.COM "))), pool, "sid", 0, confirm=True)
    assert pool.calls == [("dana@spa.com", "hunter")] and db.tables["leads"][0]["owner_email"] == "dana@spa.com"


def test_malformed_paste_fails_without_spend(sheet):
    db = FakeDB([L("a")])
    waiting(db, "a")
    pool = Pool()
    out = run_queue(db, sheet(tab(trow("a", "not an email"))), pool, "sid", 0, confirm=True)
    assert state(db, "a") == "failed" and out["failed"] == 1 and not pool.calls and db.tables["leads"][0]["status"] == "no_buyer"


def test_hunter_error_for_one_row_leaves_it_waiting_and_continues(sheet):
    db = FakeDB([L("a"), L("b")])
    waiting(db, "a", "b")

    class Flaky(Pool):
        def verify_email(self, email, bucket):
            if email == "ann@spa.com":
                raise RuntimeError("hunter 500")
            return super().verify_email(email, bucket)
    svc = sheet(tab(trow("a", "ann@spa.com"), trow("b", "bob@spa.com")))
    out = run_queue(db, svc, Flaky(), "sid", 2, confirm=True)
    assert state(db, "a") == "waiting" and state(db, "b") == "verified" and out["errors"] == 1 and out["enriched"] == 1
    assert [(r[6], r[4]) for r in svc.written] == [("a", "ann@spa.com")]


def test_queue_reuses_the_shared_agent_helper_and_batch_name():
    from gtm import sheet_import
    assert sheet_queue._agent is sheet_import._agent and sheet_queue.BATCH_NAME is sheet_import.BATCH_NAME
