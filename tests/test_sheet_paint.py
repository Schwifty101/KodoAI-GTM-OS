import pytest

from gtm import settings_store, sheet_paint
from gtm.sheet import SheetRow
from gtm.sheet_paint import desired_colour, is_ours, plan_paint, run_paint


@pytest.mark.parametrize("status,name,email,qs,want", [
    ("sent", None, None, None, "green"), ("replied", None, None, None, "green"), ("booked", None, None, None, "green"),
    ("rejected", None, None, None, "red"), ("suppressed", None, None, None, "red"),
    ("bounced", None, None, None, "red"), ("unsubscribed", None, None, None, "red"),
    ("no_buyer", None, None, None, "red"),
    ("no_buyer", "Ann Lee", "a@x.com", None, "red"),
    ("no_buyer", "Ann Lee", None, "waiting", None),
    ("no_buyer", "Ann Lee", None, None, None),
    ("no_buyer", "Ann Lee", None, "failed", "red"),
    *[(s, None, None, None, None) for s in ("scraped", "cleaned", "enriched", "signalled", "selected", "drafted")],
])
def test_desired_colour_table(status, name, email, qs, want):
    assert desired_colour(status, name, email, qs) == want


def row(desired, written=None, no=5, width=3, tab="Utah", block=1, key="k"):
    return {"tab": tab, "block": block, "row_key": key, "sheet_row_no": no, "width": width,
            "colour_written": written, "desired": desired}


def live_of(r, colours):
    return {(r["tab"], r["block"], r["row_key"]): colours}


def test_os_paint_is_recognised_only_when_every_cell_matches():
    assert is_ours(["red"] * 3, 3, "red")
    assert not is_ours(["red", "red", None], 3, "red")
    assert not is_ours(["red", "red"], 3, "red")  # row shorter than width
    assert not is_ours(["red", "green", "red"], 3, "red")
    assert not is_ours([None] * 3, 3, None)  # nothing written, nothing ours
    assert is_ours(["red"] * 5, 3, "red")  # only columns 1..width count


def test_owner_painted_row_is_never_overwritten():
    r = row("green")
    assert plan_paint([r], live_of(r, ["red", "red", "red"])) == []  # owner red, OS wants green
    assert plan_paint([r], live_of(r, ["green", None, None])) == []  # partial owner mark
    r2 = row("red", written="red")
    assert plan_paint([r2], live_of(r2, ["green"] * 3)) == []  # owner recoloured our paint


def test_blank_row_is_painted_and_width_is_kept():
    r = row("green", width=3)
    assert plan_paint([r], live_of(r, [None] * 3)) == [("Utah", 5, 3, "green")]
    assert plan_paint([r], live_of(r, [])) == [("Utah", 5, 3, "green")]


def test_paint_width_follows_the_block_header_not_a_fixed_ten_columns():
    r = row("red", width=16, block=2)
    assert plan_paint([r], live_of(r, [None] * 16)) == [("Utah", 5, 16, "red")]
    r7 = row("red", width=7)
    assert plan_paint([r7], live_of(r7, [None])) == [("Utah", 5, 7, "red")]


def test_already_as_desired_is_skipped():
    r = row("red", written="red")
    assert plan_paint([r], live_of(r, ["red"] * 3)) == []


def test_owner_cleared_os_paint_is_left_alone_until_state_changes():
    r = row("red", written="red")
    assert plan_paint([r], live_of(r, [None] * 3)) == []
    r = row("green", written="red")  # state moved, row now blank: repaint
    assert plan_paint([r], live_of(r, [None] * 3)) == [("Utah", 5, 3, "green")]


def test_retried_no_buyer_that_becomes_enriched_loses_its_os_red():
    r = row(None, written="red")
    assert plan_paint([r], live_of(r, ["red"] * 3)) == [("Utah", 5, 3, None)]
    assert plan_paint([r], live_of(r, [None] * 3)) == []  # nothing left to clear


def test_queue_tab_and_untracked_leads_are_never_painted():
    q = row("red", tab="Queue")
    assert plan_paint([q], live_of(q, [None] * 3)) == []
    r = row("red")
    assert plan_paint([r], {}) == []  # no live row seen: nothing to paint


class FakeDb:
    def __init__(self, value=None):
        self.value, self.updates = value, []

    def table(self, name):
        self.name = name
        return self

    def select(self, *a):
        return self

    def eq(self, col, val):
        self.filt = (col, val)
        return self

    def update(self, data):
        self.upd = data
        return self

    def execute(self):
        if self.name == "settings":
            class R:
                data = [{"value": self.value}] if self.value is not None else []
            return R()
        self.updates.append((self.filt, self.upd))


def test_writeback_switch_off_refuses():
    settings_store.clear_cache()
    with pytest.raises(RuntimeError, match="off"):
        run_paint(FakeDb(False), object(), "sid", confirm=True)
    settings_store.clear_cache()
    with pytest.raises(RuntimeError, match="off"):
        run_paint(FakeDb(None), object(), "sid")  # default is off


def test_run_paint_previews_then_paints_and_records(monkeypatch, capsys):
    settings_store.clear_cache()
    r = {**row("red"), "id": "row-1"}
    monkeypatch.setattr(sheet_paint, "_tracked_and_live", lambda db, svc, sid: ([r], live_of(r, [None] * 3), 2))
    painted = []
    monkeypatch.setattr(sheet_paint, "paint_rows", lambda svc, sid, tab, cells: painted.append((tab, cells)) or len(cells))
    db = FakeDb(True)
    assert run_paint(db, object(), "sid") == 1
    assert painted == [] and db.updates == []
    out = capsys.readouterr().out
    assert "Utah" in out and "2 rows moved" in out
    assert run_paint(db, object(), "sid", confirm=True) == 1
    assert painted == [("Utah", [(5, 3, "red")])]
    (filt, upd), = db.updates
    assert filt == ("id", "row-1") and upd["colour_written"] == "red" and upd["written_at"]
    settings_store.clear_cache()


class Q:
    """Fake query chain over a list of rows (join already embedded)."""
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "sheet_rows"
        return self

    def __getattr__(self, name):  # select, not_, is_, eq, order: all return the chain
        return self if name == "not_" else (lambda *a, **k: self)

    def range(self, lo, hi):
        self.lo, self.hi = lo, hi
        return self

    def execute(self):
        class R:
            data = self.rows[self.lo:self.hi + 1]
        return R()


def _sr(no, name, site):
    return SheetRow("Utah", no, [name, f"https://{site}"], [None] * 2)


def _tr(id_, no, site, status="sent", block=1):
    return {"id": id_, "tab": "Utah", "block": block, "row_key": f"domain:{site}", "sheet_row_no": no,
            "colour_written": None, "queue_state": None,
            "leads": {"status": status, "owner_name": None, "owner_email": None}}


def test_tracked_and_live_joins_width_and_skips_moved_and_blank_rows(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             _sr(2, "Glow", "glow.example"),             # tracked row 2 is still here
             _sr(3, "Other", "other.example")]           # tracked row 3 moved: another lead's row sits there
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: sheet)
    data = [_tr("a", 2, "glow.example"), _tr("b", 3, "moved.example"), _tr("c", 9, "gone.example")]  # 9: no row
    tracked, live, moved = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert [t["id"] for t in tracked] == ["a"] and tracked[0]["width"] == 2 and tracked[0]["desired"] == "green"
    assert live == {("Utah", 1, "domain:glow.example"): [None, None]}
    assert moved == 2
    assert plan_paint(tracked, live) == [("Utah", 2, 2, "green")]  # moved row 3 and missing row 9 are never painted
