import pytest

from gtm import sheet_format as sf

G, R = {"red": 0, "green": 1, "blue": 0}, {"red": 1, "green": 0, "blue": 0}
PASTEL = {"red": 0.85, "green": 0.95, "blue": 0.85}


def cell(text="x", bg=None):
    v = {"formattedValue": text}
    if bg:
        v["userEnteredFormat"] = {"backgroundColor": bg}
    return v


def sheet(title, rows, cf=None, tables=None, gid=7):
    return {"properties": {"sheetId": gid, "title": title}, "conditionalFormats": cf or [], "tables": tables or [],
            "data": [{"rowData": [{"values": r} for r in rows]}]}


HDR = [cell("business"), cell("website"), cell("email")]


class Svc:
    def __init__(self, *gets):
        self.gets, self.batches = list(gets), []

    def spreadsheets(self):
        return self

    def get(self, **kw):
        self.last = self.gets.pop(0) if len(self.gets) > 1 else self.gets[0]
        return self

    def batchUpdate(self, spreadsheetId, body):
        self.batches.append(body["requests"])
        return self

    def execute(self):
        return self.last if hasattr(self, "last") else {}


@pytest.fixture(autouse=True)
def snapdir(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "SECRETS", tmp_path)


def writes(svc):
    return [r["repeatCell"] for b in svc.batches for r in b if "repeatCell" in r]


def test_partial_mark_becomes_full_row_mark():
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(), cell("s", G), cell()]])]})
    sf.run_format(svc, "id", confirm=True)
    w = [r for r in writes(svc) if r["range"]["startRowIndex"] == 1]
    assert w[0]["cell"]["userEnteredFormat"]["backgroundColor"] == {"red": 0, "green": 1, "blue": 0}
    assert (w[0]["range"]["startColumnIndex"], w[0]["range"]["endColumnIndex"]) == (0, 3)


def test_green_and_red_row_becomes_red():
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(bg=G), cell(bg=R), cell()]])]})
    sf.run_format(svc, "id", confirm=True)
    w = [r for r in writes(svc) if r["range"]["startRowIndex"] == 1]
    assert w[0]["cell"]["userEnteredFormat"]["backgroundColor"] == {"red": 1, "green": 0, "blue": 0}


def test_pastel_cell_is_cleared():
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(bg=PASTEL), cell(), cell()]])]})
    sf.run_format(svc, "id", confirm=True)
    w = [r for r in writes(svc) if r["range"]["startRowIndex"] == 1]
    assert w[0]["cell"] == {"userEnteredFormat": {}} and w[0]["fields"] == "userEnteredFormat.backgroundColor"


def test_full_pure_red_row_is_not_touched():
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(bg=R), cell(bg=R), cell(bg=R)]])]})
    sf.run_format(svc, "id", confirm=True)
    assert [r for r in writes(svc) if r["range"]["startRowIndex"] == 1] == []


def test_headers_styled_including_second_block():
    rows = [HDR, [cell(), cell(), cell()], [cell("Company"), cell("x")], [cell("a"), cell("b")]]
    svc = Svc({"sheets": [sheet("Utah", rows)]})
    sf.run_format(svc, "id", confirm=True)
    hdr = [r for r in writes(svc) if "textFormat" in r["cell"]["userEnteredFormat"]]
    assert [(h["range"]["startRowIndex"], h["range"]["endColumnIndex"]) for h in hdr] == [(0, 3), (2, 2)]
    f = hdr[0]["cell"]["userEnteredFormat"]
    assert f["backgroundColor"] == {"red": 0.2, "green": 0.2, "blue": 0.2} and f["textFormat"]["bold"] is True


def test_conditional_rules_deleted_highest_index_first():
    rng = {"startRowIndex": 0, "endRowIndex": 50}
    cf = [{"ranges": [rng]}, {"ranges": [{"startRowIndex": 100, "endRowIndex": 101}]}, {"ranges": [rng]}]
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(), cell(), cell()]], cf=cf)]})
    sf.run_format(svc, "id", confirm=True)
    assert [r["deleteConditionalFormatRule"]["index"] for b in svc.batches for r in b if "deleteConditionalFormatRule" in r] == [2, 0]


def test_dry_run_issues_no_batch_update_or_snapshot(tmp_path):
    svc = Svc({"sheets": [sheet("Utah", [HDR, [cell(), cell("s", G), cell()]], tables=[{"name": "Table_1"}])]})
    sf.run_format(svc, "id")
    assert svc.batches == [] and list(tmp_path.iterdir()) == []


def test_lost_mark_after_write_fails_loudly(tmp_path, capsys):
    before = {"sheets": [sheet("Utah", [HDR, [cell(), cell("s", G), cell()]])]}
    after = {"sheets": [sheet("Utah", [HDR, [cell(), cell("s"), cell()]])]}
    with pytest.raises(SystemExit) as e:
        sf.run_format(Svc(before, after), "id", confirm=True)
    assert e.value.code == 1 and "FAIL" in capsys.readouterr().out
    assert len(list(tmp_path.glob("sheet_marks_snapshot_*.json"))) == 1


def test_queue_tab_skipped_and_never_written():
    svc = Svc({"sheets": [sheet("Queue", [[cell("business")], [cell("a", G)]], gid=9), sheet("Utah", [HDR, [cell(), cell(), cell()]])]})
    sf.run_format(svc, "id", confirm=True)
    assert svc.batches and all(r["repeatCell"]["range"]["sheetId"] == 7 for b in svc.batches for r in b)
    with pytest.raises(ValueError):
        sf.run_format(svc, "id", tab="Queue")
