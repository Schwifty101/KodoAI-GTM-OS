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


def test_read_tab_real_api_400_for_missing_tab_raises_value_error():
    from googleapiclient.errors import HttpError

    class Resp:
        status, reason = 400, "Bad Request"

    class Boom(FakeSvc):
        def execute(self):
            raise HttpError(Resp(), b'{"error": {"message": "Unable to parse range: \'Nope\'!A:Z"}}')

    with pytest.raises(ValueError, match="tab 'Nope' not found in sheet"):
        read_tab(Boom(None), "SID", "Nope")

    class Resp500(Resp):
        status = 500

    class Boom500(FakeSvc):
        def execute(self):
            raise HttpError(Resp500(), b"{}")

    with pytest.raises(HttpError):
        read_tab(Boom500(None), "SID", "Nope")


def test_read_tab_escapes_apostrophe_in_tab_title():
    svc = FakeSvc(_resp([_cell("a")], title="Bob's"))
    read_tab(svc, "SID", "Bob's")
    assert svc.calls[0]["ranges"] == ["'Bob''s'!A:Z"]


def test_revoked_refresh_token_raises_runtime_error(tmp_path, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    class Dead:
        expired, refresh_token, valid = True, "r", False

        def refresh(self, _request):
            raise RefreshError("invalid_grant")

    (tmp_path / "token_sheets.json").write_text("{}")
    monkeypatch.setattr(sheet, "SECRETS", tmp_path)
    monkeypatch.setattr(Credentials, "from_authorized_user_file", classmethod(lambda cls, *a, **k: Dead()))
    with pytest.raises(RuntimeError, match="token_sheets.json"):
        sheet.sheets_service()


def test_headless_without_token_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sheet, "SECRETS", tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(RuntimeError, match="token_sheets.json"):
        sheet.sheets_service()


class RecSvc:
    """Records every request; get() returns the given tab titles."""

    def __init__(self, titles=("Texas",)):
        self.titles, self.log = list(titles), []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def _rec(self, name, kw):
        self.log.append((name, kw))
        return self

    def get(self, **kw):
        return self._rec("get", kw)

    def batchUpdate(self, **kw):
        return self._rec("batchUpdate", kw)

    def clear(self, **kw):
        return self._rec("clear", kw)

    def update(self, **kw):
        return self._rec("update", kw)

    def execute(self):
        name = self.log[-1][0]
        if name == "get":
            return {"sheets": [{"properties": {"title": t, "sheetId": 100 + i}} for i, t in enumerate(self.titles)]}
        return {}

    def names(self):
        return [n for n, _ in self.log]


def test_paint_rows_builds_one_batch_with_pure_colours():
    svc = RecSvc(["Other", "Texas"])
    assert sheet.paint_rows(svc, "SID", "Texas", [(3, 10, "green"), (7, 4, "red")]) == 2
    batches = [kw for n, kw in svc.log if n == "batchUpdate"]
    assert len(batches) == 1 and batches[0]["spreadsheetId"] == "SID"
    r1, r2 = batches[0]["body"]["requests"]
    assert r1["repeatCell"]["range"] == {"sheetId": 101, "startRowIndex": 2, "endRowIndex": 3,
                                         "startColumnIndex": 0, "endColumnIndex": 10}
    assert r1["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"] == {"red": 0, "green": 1, "blue": 0}
    assert r1["repeatCell"]["fields"] == "userEnteredFormat.backgroundColor"
    assert r2["repeatCell"]["range"]["startRowIndex"] == 6 and r2["repeatCell"]["range"]["endColumnIndex"] == 4
    assert r2["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"] == {"red": 1, "green": 0, "blue": 0}


def test_paint_clear_uses_white():
    svc = RecSvc()
    assert sheet.paint_rows(svc, "SID", "Texas", [(2, 10, None)]) == 1
    bg = svc.log[-1][1]["body"]["requests"][0]["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"]
    assert bg == {"red": 1, "green": 1, "blue": 1}


def test_write_queue_tab_creates_tab_when_missing():
    svc = RecSvc(["Texas"])
    sheet.write_queue_tab(svc, "SID", [["a"]])
    add = [kw for n, kw in svc.log if n == "batchUpdate"][0]["body"]["requests"]
    assert add == [{"addSheet": {"properties": {"title": "Queue"}}}]


def test_write_queue_tab_clears_then_writes_header_and_rows():
    svc = RecSvc(["Queue"])
    sheet.write_queue_tab(svc, "SID", [["biz", "Ann", "x.com", "u", "", "waiting", "id1"]])
    assert "batchUpdate" not in svc.names()
    assert svc.names()[-2:] == ["clear", "update"]
    assert dict(svc.log)["clear"]["range"] == "Queue!A:G"
    up = dict(svc.log)["update"]
    assert up["range"] == "Queue!A1" and up["valueInputOption"] == "RAW"
    header = ["business", "owner_name", "domain", "linkedin_search", "email", "status", "lead_id"]
    assert up["body"]["values"] == [header,["biz", "Ann", "x.com", "u", "", "waiting", "id1"]]


def test_read_tab_keeps_colours_of_trailing_format_only_cells():
    g = {"green": 1}
    svc = FakeSvc(_resp([_cell(c, g) for c in "abcde"] + [_cell(None, g) for _ in range(5)]))
    row = read_tab(svc, "SID", "Texas")[0]
    assert row.cells == list("abcde") and row.colours == ["green"] * 10
