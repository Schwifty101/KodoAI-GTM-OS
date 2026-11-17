import sys

import pytest

from gtm import sheet
from gtm.sheet import SheetRow, colour_of, read_tab


def test_colour_of_pure_green_red_only():
    assert colour_of({"green": 1}) == "green"
    assert colour_of({"red": 1}) == "red"
    assert colour_of({"red": 0.01, "green": 0.99, "blue": 0.01}) == "green"
    for bg in [{"red": 0.72, "green": 0.88, "blue": 0.8}, {"red": 0.97, "green": 0.84, "blue": 0.85},
               {"red": 1, "green": 0.95, "blue": 0.8}, {"red": 0.24, "green": 0.52, "blue": 0.78},
               {"red": 1, "green": 1, "blue": 1}, {}, None]:
        assert colour_of(bg) is None


class FakeSvc:
    def __init__(self, response):
        self.response, self.calls = response, []

    def spreadsheets(self):
        return self

    def get(self, **kw):
        self.calls.append(kw)
        return self

    def execute(self):
        return self.response


def _cell(v=None, bg=None):
    c = {}
    if v is not None:
        c["formattedValue"] = v
    if bg is not None:
        c["userEnteredFormat"] = {"backgroundColor": bg}
    return c


def _resp(*rows, title="Texas"):
    return {"sheets": [{"properties": {"title": title}, "data": [{"rowData": [{"values": r} for r in rows]}]}]}


def test_read_tab_ignores_effective_format():
    svc = FakeSvc(_resp([_cell("a", {"green": 1}), _cell("b")]))
    rows = read_tab(svc, "SID", "Texas")
    assert rows == [SheetRow("Texas", 1, ["a", "b"], ["green", None])]
    kw = svc.calls[0]
    assert kw["spreadsheetId"] == "SID" and kw["includeGridData"] is True and kw["ranges"] == ["'Texas'!A:Z"]
    assert kw["fields"] == "sheets.data.rowData.values(formattedValue,userEnteredFormat.backgroundColor)"
    assert "effectiveFormat" not in kw["fields"]


def test_read_tab_skips_blank_rows_and_numbers_rows_from_1():
    svc = FakeSvc(_resp([_cell("h"), _cell()], [{}, _cell(" ")], [_cell(), _cell(5, {"red": 1})], {}, [_cell("z")]))
    rows = read_tab(svc, "SID", "Texas")
    assert [r.row_no for r in rows] == [1, 3, 5]
    assert rows[0].cells == ["h"]  # padded only to the last value
    assert rows[1].cells == ["", "5"] and rows[1].colours == [None, "red"]


def test_read_tab_missing_tab_raises_value_error():
    with pytest.raises(ValueError, match="tab 'Nope' not found in sheet"):
        read_tab(FakeSvc({"sheets": []}), "SID", "Nope")


def test_headless_without_token_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet, "SECRETS", tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(RuntimeError, match="token_sheets.json"):
        sheet.sheets_service()
