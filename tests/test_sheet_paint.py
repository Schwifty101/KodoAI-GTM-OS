import pytest

from gtm import settings_store, sheet_paint
from gtm.sheet import SheetRow
from gtm.sheet_paint import desired_colour, is_ours, os_col, os_status_value, plan_paint, plan_status, run_paint


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


@pytest.mark.parametrize("status,name,email,qs,want", [
    ("sent", None, None, None, "sent"), ("replied", None, None, None, "sent"), ("rejected", None, None, None, "dropped"),
    ("no_buyer", "Ann Lee", None, "waiting", "open"), ("no_buyer", "Ann Lee", None, "failed", "dropped"),
    ("signalled", None, None, None, "open"),
])
def test_os_status_value_table(status, name, email, qs, want):
    assert os_status_value(status, name, email, qs) == want


def test_os_col_finds_existing_or_appends_after_last_header():
    assert os_col([f"h{i}" for i in range(20)]) == (20, False)
    assert os_col([f"h{i}" for i in range(21)] + ["os_status"]) == (21, True)
    assert os_col(["a", "", "b", ""]) == (3, False)


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
    r = {**row("red"), "id": "row-1", "stored_row_no": 7}
    monkeypatch.setattr(sheet_paint, "_tracked_and_live", lambda db, svc, sid: ([r], live_of(r, [None] * 3), 2, {}, {}))
    painted = []
    monkeypatch.setattr(sheet_paint, "paint_rows", lambda svc, sid, tab, cells: painted.append((tab, cells)) or len(cells))
    db = FakeDb(True)
    assert run_paint(db, object(), "sid") == 1
    assert painted == [] and db.updates == []
    out = capsys.readouterr().out
    assert "Utah" in out and "2 rows moved" in out
    assert run_paint(db, object(), "sid", confirm=True) == 1
    assert painted == [("Utah", [(5, 3, "red")])]
    assert (("id", "row-1"), {"sheet_row_no": 5}) in db.updates  # stored row 7 followed the owner's sort to live row 5
    filt, upd = db.updates[-1]
    assert filt == ("id", "row-1") and upd["colour_written"] == "red" and upd["colour_seen"] == "red" and upd["written_at"]
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


def test_tracked_and_live_joins_width_and_skips_missing_and_blank_rows(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             _sr(2, "Glow", "glow.example"),
             _sr(3, "Other", "other.example")]
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: sheet)
    data = [_tr("a", 2, "glow.example"), _tr("c", 9, "gone.example")]  # gone.example is not in the tab
    tracked, live, moved, *_ = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert [t["id"] for t in tracked] == ["a"] and tracked[0]["width"] == 2 and tracked[0]["desired"] == "green"
    assert live == {("Utah", 1, "domain:glow.example"): [None, None]}
    assert moved == 1
    assert plan_paint(tracked, live) == [("Utah", 2, 2, "green")]


def test_sorted_tab_rows_are_found_by_key(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             _sr(2, "B", "b.example"), _sr(3, "A", "a.example"), _sr(4, "C", "c.example")]  # a and b swapped
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: sheet)
    data = [_tr("a", 5, "a.example"), _tr("b", 6, "b.example", status="rejected")]
    tracked, live, moved, *_ = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert {t["id"]: (t["sheet_row_no"], t["stored_row_no"]) for t in tracked} == {"a": (3, 5), "b": (2, 6)}
    assert moved == 0
    assert sorted(plan_paint(tracked, live)) == [("Utah", 2, 2, "red"), ("Utah", 3, 2, "green")]


def test_missing_or_duplicate_key_is_skipped_and_counted(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             _sr(2, "A", "a.example"), _sr(3, "A again", "a.example"), _sr(4, "C", "c.example")]
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: sheet)
    data = [_tr("a", 2, "a.example"), _tr("gone", 5, "gone.example"), _tr("c", 4, "c.example")]
    tracked, live, moved, *_ = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert [t["id"] for t in tracked] == ["c"] and moved == 2


def _st(value, no=5, key="k"):
    return {"tab": "Utah", "block": 1, "row_key": key, "sheet_row_no": no, "status_value": value}


def test_plan_status_only_where_different():
    a, b, c = _st("sent", 2, "a"), _st("open", 3, "b"), _st("dropped", 4, "c")
    live = {("Utah", 1, "a"): "sent", ("Utah", 1, "b"): "", ("Utah", 1, "c"): "dropped"}  # b: owner cleared the cell
    assert plan_status([a, b, c], live, {"Utah": 20}) == [("Utah", 3, 20, "open")]
    assert plan_status([a], {("Utah", 1, "a"): "typed by owner"}, {"Utah": 20}) == [("Utah", 2, 20, "sent")]
    assert plan_status([a], {("Utah", 1, "a"): ""}, {}) == []  # tab without a status column: nothing


def test_suppression_only_row_takes_value_from_its_colour(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2), _sr(2, "A", "a.example"), _sr(3, "B", "b.example")]
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: sheet)
    data = [{**_tr("a", 2, "a.example"), "leads": None, "suppression_id": "s1", "colour_seen": "green"},
            {**_tr("b", 3, "b.example"), "leads": None, "suppression_id": "s2", "colour_seen": "red"}]
    tracked, live, moved, live_status, hdr = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert {t["id"]: t["status_value"] for t in tracked} == {"a": "sent", "b": "dropped"}
    assert plan_paint(tracked, live) == []  # owner marks are never repainted
    assert hdr == {"Utah": (1, 2, False)}  # header row 1, os_status goes to column C (index 2)


def _patch_paint(monkeypatch, hdr_exists):
    r = {**row("red"), "id": "row-1", "stored_row_no": 5, "status_value": "dropped"}
    monkeypatch.setattr(sheet_paint, "_tracked_and_live", lambda db, svc, sid: (
        [r], live_of(r, [None] * 3), 0, {("Utah", 1, "k"): ""}, {"Utah": (1, 20, hdr_exists)}))
    calls = {"paint": [], "cells": []}
    monkeypatch.setattr(sheet_paint, "paint_rows", lambda svc, sid, tab, cells: calls["paint"].append(cells) or len(cells))
    monkeypatch.setattr(sheet_paint, "write_cells", lambda svc, sid, tab, cells: calls["cells"].append(cells) or len(cells))
    return calls


def test_preview_prints_colour_and_status_changes_separately_and_writes_nothing(monkeypatch, capsys):
    settings_store.clear_cache()
    calls = _patch_paint(monkeypatch, False)
    db = FakeDb(True)
    assert run_paint(db, object(), "sid") == 1
    assert calls == {"paint": [], "cells": []} and db.updates == []
    out = capsys.readouterr().out
    assert "Utah row 5 (A..3): red" in out and "Utah row 5: os_status dropped" in out and "1 status cells" in out
    settings_store.clear_cache()


def test_confirm_writes_header_once_then_values(monkeypatch):
    settings_store.clear_cache()
    calls = _patch_paint(monkeypatch, False)
    run_paint(FakeDb(True), object(), "sid", confirm=True)
    assert calls["cells"] == [[(1, 20, "os_status"), (5, 20, "dropped")]]
    calls = _patch_paint(monkeypatch, True)  # header exists: values only
    run_paint(FakeDb(True), object(), "sid", confirm=True)
    assert calls["cells"] == [[(5, 20, "dropped")]]
    settings_store.clear_cache()


def _sheet(monkeypatch, rows):
    monkeypatch.setattr(sheet_paint, "read_tab", lambda svc, sid, tab: rows)


def test_os_status_header_does_not_widen_the_paint_width(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website", "os_status"], [None] * 3),
             SheetRow("Utah", 2, ["A", "https://a.example", "open"], ["red", "red", None])]  # our earlier paint, A..2
    _sheet(monkeypatch, sheet)
    rec = {**_tr("a", 2, "a.example"), "colour_written": "red"}  # lead is now sent: repaint green
    tracked, live, moved, live_status, hdr = sheet_paint._tracked_and_live(Q([rec]), object(), "sid")
    assert tracked[0]["width"] == 2 and hdr == {"Utah": (1, 2, True)}
    assert plan_paint(tracked, live) == [("Utah", 2, 2, "green")]  # recognised as ours, not an owner mark


def test_missing_os_status_goes_past_the_longest_row_of_the_tab(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             SheetRow("Utah", 2, ["A", "https://a.example", "", "", "note"], [None] * 5)]
    _sheet(monkeypatch, sheet)
    _, _, _, _, hdr = sheet_paint._tracked_and_live(Q([_tr("a", 2, "a.example")]), object(), "sid")
    assert hdr == {"Utah": (1, 5, False)}


def test_one_live_row_claimed_by_two_records_is_skipped_and_counted(monkeypatch):
    _sheet(monkeypatch, [SheetRow("Utah", 1, ["business", "website"], [None] * 2), _sr(2, "A", "a.example")])
    data = [_tr("b1", 2, "a.example", block=1), _tr("b2", 2, "a.example", block=2)]
    tracked, live, moved, *_ = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert tracked == [] and moved == 2


def test_owner_mark_decides_os_status(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             SheetRow("Utah", 2, ["A", "https://a.example"], ["red", "red"]),
             SheetRow("Utah", 3, ["B", "https://b.example"], ["green", "green"])]
    _sheet(monkeypatch, sheet)
    data = [_tr("a", 2, "a.example", status="sent"), _tr("b", 3, "b.example", status="rejected")]
    tracked, live, *_ = sheet_paint._tracked_and_live(Q(data), object(), "sid")
    assert {t["id"]: t["status_value"] for t in tracked} == {"a": "dropped", "b": "sent"}
    assert plan_paint(tracked, live) == []


def test_status_column_past_az_is_refused(monkeypatch):
    sheet = [SheetRow("Utah", 1, ["business", "website"], [None] * 2),
             SheetRow("Utah", 2, ["A", "https://a.example"] + [""] * 49 + ["far"], [None] * 52)]
    _sheet(monkeypatch, sheet)
    with pytest.raises(RuntimeError, match="past AZ"):
        sheet_paint._tracked_and_live(Q([_tr("a", 2, "a.example")]), object(), "sid")


def test_preview_skips_stored_row_number_update(monkeypatch):
    settings_store.clear_cache()
    r = {**row("red"), "id": "row-1", "stored_row_no": 7, "status_value": "dropped"}
    monkeypatch.setattr(sheet_paint, "_tracked_and_live", lambda db, svc, sid: ([r], live_of(r, [None] * 3), 0, {}, {}))
    db = FakeDb(True)
    run_paint(db, object(), "sid")
    assert db.updates == []
    settings_store.clear_cache()
