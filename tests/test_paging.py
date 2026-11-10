import pytest

from gtm.db import fetch_all, get_db
from gtm.select import _blocklists


class FakeQuery:
    """Stands in for a PostgREST query that returns at most the rows inside the requested range."""

    def __init__(self, rows):
        self.rows, self.ranges, self.lo, self.hi = rows, [], 0, 0

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        self.ranges.append((lo, hi))
        return self

    def execute(self):
        return type("R", (), {"data": self.rows[self.lo : self.hi + 1]})()


def test_fetch_all_pages_past_the_1000_row_api_cap():
    rows = [{"id": i} for i in range(2500)]
    q = FakeQuery(rows)
    assert fetch_all(lambda: q) == rows
    assert q.ranges == [(0, 999), (1000, 1999), (2000, 2999)]


def test_fetch_all_handles_an_exact_page_boundary_and_empty_results():
    rows = [{"id": i} for i in range(2000)]
    assert fetch_all(lambda: FakeQuery(rows)) == rows
    assert fetch_all(lambda: FakeQuery([])) == []


@pytest.mark.db
def test_blocklists_sees_suppression_rows_past_the_1000_row_api_cap():
    """Anti-goal: an opt-out beyond row 1000 must still block. The API returns 1000 rows per request unless the caller pages."""
    db = get_db()
    emails = [f"pytest-page-{i}@example.com" for i in range(1100)]
    try:
        for i in range(0, 1100, 550):
            db.table("suppression").insert([{"email": e, "reason": "pytest-paging"} for e in emails[i : i + 550]]).execute()
        suppressed, _ = _blocklists(db)
        assert set(emails) <= suppressed
    finally:
        db.table("suppression").delete().eq("reason", "pytest-paging").execute()
