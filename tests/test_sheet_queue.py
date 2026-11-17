import itertools
from types import SimpleNamespace

from gtm import sheet_queue
from gtm.sheet_queue import pull_sheet_only, queue_order, select_queue

_ids = itertools.count(1)


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
        self.rows = [r for r in self.rows if r.get(k) in vs]
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

    upsert = lambda self, rows, **k: self.insert(rows)  # noqa: E731

    def execute(self):
        if self.mode == "update":
            for r in self.rows:
                r.update(self.patch)
        elif self.mode == "insert":
            self.rows = [{"id": f"id{next(_ids)}", **r} for r in self.patch]
            self.tables[self.name].extend(self.rows)
        return SimpleNamespace(data=self.rows)


class FakeDB:
    def __init__(self, leads=(), sheet_rows=(), suppression=(), touches=()):
        self.tables = {"leads": list(leads), "sheet_rows": list(sheet_rows), "suppression": list(suppression), "touches": list(touches), "batches": []}

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
