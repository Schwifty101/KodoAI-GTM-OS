import pytest

from gtm import sheet_format as sf

G, R = {"red": 0, "green": 1, "blue": 0}, {"red": 1, "green": 0, "blue": 0}
PASTEL = {"red": 0.85, "green": 0.95, "blue": 0.85}


def cell(text="x", bg=None):
    v = {"formattedValue": text}
    if bg:
        v["userEnteredFormat"] = {"backgroundColor": bg}
    return v


def sheet(title, rows, cf=None, tables=None, gid=7, cols=26, **extra):
    return {"properties": {"sheetId": gid, "title": title, "gridProperties": {"columnCount": cols}}, "conditionalFormats": cf or [], "tables": tables or [],
            "data": [{"rowData": [{"values": r} for r in rows]}], **extra}


HDR = [cell("business"), cell("website"), cell("email")]


def full(*sheets):
    return {"sheets": list(sheets)}


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
    svc = Svc({"sheets": [sheet("Newyork", rows)]})  # no merge target: both headers stay and both are styled
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


# ---- step F: merge blocks ----
from gtm.sheet_map import MERGE_TARGET

H1 = "business,maps_category,website,buyer_name,buyer_role,linkedin_url,email,email_person,other_people,maps_url".split(",")
H2 = ["Company", "City", "Website", "Fit", "Buyer", "Role", "Role check", "Role evidence (quote)", "Role evidence URL",
      "LinkedIn (confirmed)", "LinkedIn (to check)", "Email", "Email type", "Email status", "Email source", "Notes"]
SRC_TO_TARGET = {0: 0, 1: 10, 2: 2, 3: 11, 4: 3, 5: 4, 6: 12, 7: 13, 8: 14, 9: 5, 10: 15, 11: 6, 12: 16, 13: 17, 14: 18, 15: 19}


def b1_rows():
    return [[cell(h) for h in H1]] + [[cell(f"a{i}_{j}") for j in range(10)] for i in range(18)]  # rows 1-19


def b2_rows():
    rows = [[cell(h) for h in H2]]  # row 20
    for i in range(26):  # rows 21-46
        rows.append([cell(f"c{i}_{j}", G if (i, j) == (3, 4) else R if (i, j) == (5, 0) else None) for j in range(16)])
    return rows


def merged_rows(tamper=None):
    out = [[cell(h) for h in MERGE_TARGET["Utah"]]] + b1_rows()[1:]
    for r in b2_rows()[1:]:
        new = [cell("") for _ in range(20)]
        for c, t in SRC_TO_TARGET.items():
            new[t] = r[c]
        out.append(new)
    if tamper:
        tamper(out)
    return out


def merge_states(tamper=None):
    return full(sheet("Utah", b1_rows() + b2_rows())), full(sheet("Utah", merged_rows(tamper)))


def test_merge_dry_run_reports_and_writes_nothing(capsys):
    before, _ = merge_states()
    svc = Svc(before)
    sf.run_format(svc, "id")
    out = capsys.readouterr().out
    assert svc.batches == []
    assert "2 blocks -> 1: block 2 rows 20-46 (27 rows) merged under block 1; columns added: city, fit," in out


def test_merge_request_order_and_ranges():
    before, after = merge_states()
    svc = Svc(before, after, after)
    sf.run_format(svc, "id", confirm=True)
    first = svc.batches[0]
    kinds_ = [next(iter(r)) for r in first]
    assert kinds_ == ["appendDimension", "deleteDimension", *["cutPaste"] * 28, "updateCells", "deleteDimension"]
    assert first[0]["appendDimension"] == {"sheetId": 7, "dimension": "COLUMNS", "length": 8}  # staging at T+1.. needs 34 columns
    assert first[1]["deleteDimension"]["range"] == {"sheetId": 7, "dimension": "ROWS", "startIndex": 19, "endIndex": 20}
    # pass 1: Buyer (src col 4) to staging; the data rows are now 20-45 (0-based 19..45)
    cut = first[2 + [c for c in SRC_TO_TARGET if SRC_TO_TARGET[c] != c].index(4)]["cutPaste"]
    assert cut["source"] == {"sheetId": 7, "startRowIndex": 19, "endRowIndex": 45, "startColumnIndex": 4, "endColumnIndex": 5}
    assert cut["destination"]["columnIndex"] >= 20 and cut["pasteType"] == "PASTE_NORMAL"
    # pass 2 lands every moved column on its target
    landed = {c["cutPaste"]["destination"]["columnIndex"] for c in first[16:30]}
    assert landed == {t for c, t in SRC_TO_TARGET.items() if c != t}
    hdr = first[30]["updateCells"]
    assert hdr["start"] == {"sheetId": 7, "rowIndex": 0, "columnIndex": 0}
    assert [v["userEnteredValue"]["stringValue"] for v in hdr["rows"][0]["values"]] == MERGE_TARGET["Utah"]
    assert first[31]["deleteDimension"]["range"] == {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 26, "endIndex": 34}


def test_merge_verifies_and_snapshots(tmp_path, capsys):
    before, after = merge_states()
    sf.run_format(Svc(before, after, after), "id", confirm=True)
    assert len(list(tmp_path.glob("sheet_merge_snapshot_*.json"))) == 1 and "verified: merge" in capsys.readouterr().out


def test_merge_fails_on_lost_mark_and_on_changed_value():
    def lose(rows):
        rows[22][3] = cell("c3_4")  # the green mark (Buyer, moved to column D) lost

    def change(rows):
        rows[30][2] = cell("CHANGED")
    for tamper in (lose, change):
        before, after = merge_states(tamper)
        with pytest.raises(SystemExit) as e:
            sf.run_format(Svc(before, after), "id", confirm=True)
        assert e.value.code == 1


def test_one_block_tab_untouched_by_merge():
    svc = Svc(full(sheet("Utah", b1_rows())))
    sf.run_format(svc, "id", confirm=True)
    assert not any("cutPaste" in r or "appendDimension" in r for b in svc.batches for r in b)


def test_multi_block_tab_without_target_is_left_alone(capsys):
    svc = Svc(full(sheet("Newyork", [HDR, [cell(), cell(), cell()], [cell("Company"), cell("x")], [cell("a"), cell("b")]], gid=8)))
    sf.run_format(svc, "id", confirm=True)
    assert "Newyork: 2 blocks, needs a target header; left alone" in capsys.readouterr().out
    assert not any("cutPaste" in r or "deleteDimension" in r for b in svc.batches for r in b)


# ---- fix round 1 ----
def utah(**extra):
    return full(sheet("Utah", b1_rows() + b2_rows(), **extra))


@pytest.mark.parametrize("extra", [
    {"tables": [{"name": "Table_1"}]},
    {"merges": [{"startRowIndex": 25, "endRowIndex": 26, "startColumnIndex": 0, "endColumnIndex": 2}]},
    {"basicFilter": {"range": {"startRowIndex": 0, "endRowIndex": 19}}},
    {"filterViews": [{"filterViewId": 1, "range": {}}]},
])
@pytest.mark.parametrize("confirm", [False, True])
def test_merge_blocked_by_table_merged_cells_or_filter_before_any_write(extra, confirm, capsys):
    svc = Svc(utah(**extra))
    with pytest.raises(ValueError, match="Utah"):
        sf.run_format(svc, "id", confirm=confirm)
    assert svc.batches == [] and "BLOCKED" in capsys.readouterr().out


def test_merged_range_above_block_two_does_not_block_merge():
    svc = Svc(*[utah(merges=[{"startRowIndex": 0, "endRowIndex": 2}])] * 1)
    sf.run_format(svc, "id")  # dry run: no raise


def test_formatting_blocked_by_merged_cells_in_restyled_rows(capsys):
    svc = Svc(full(sheet("Utah", [HDR, [cell(), cell("s", G), cell()]], merges=[{"startRowIndex": 1, "endRowIndex": 2}])))
    with pytest.raises(ValueError, match="Utah"):
        sf.run_format(svc, "id")
    assert svc.batches == [] and "BLOCKED" in capsys.readouterr().out


def test_grid_narrower_than_target_keeps_target_columns():
    svc = Svc(full(sheet("Utah", b1_rows() + b2_rows(), cols=15)))
    with pytest.raises(SystemExit):  # the fake never applies the write: verification fails, only the requests matter
        sf.run_format(svc, "id", confirm=True)
    first = svc.batches[0]
    assert first[0]["appendDimension"]["length"] == 19
    assert first[-1]["deleteDimension"]["range"] == {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 20, "endIndex": 34}


def test_block_one_text_past_its_header_is_refused():
    b1 = b1_rows()
    b1[4] = b1[4] + [cell("stray")]
    svc = Svc(full(sheet("Utah", b1 + b2_rows())))
    with pytest.raises(ValueError, match="Utah.*row 5"):
        sf.run_format(svc, "id", confirm=True)
    assert svc.batches == []


def test_mark_outside_block_two_header_width_is_refused(capsys):
    b2 = b2_rows()
    b2[3] = b2[3] + [cell("")] * 9 + [cell("", G)]  # colour in column Z of row 23
    svc = Svc(full(sheet("Utah", b1_rows() + b2)))
    with pytest.raises(ValueError, match="mark outside the header width at Utah row 23"):
        sf.run_format(svc, "id")
    assert "BLOCKED" in capsys.readouterr().out and svc.batches == []


def test_merge_is_its_own_run_and_skips_formatting(capsys):
    before, after = merge_states()
    svc = Svc(before, after)
    sf.run_format(svc, "id", confirm=True)
    assert len(svc.batches) == 1 and "merge done and verified; run sheet-format again for the formatting steps" in capsys.readouterr().out


def test_dry_run_with_merge_says_formatting_is_planned_after(capsys):
    sf.run_format(Svc(merge_states()[0]), "id")
    assert "formatting steps are planned after the merge: rerun" in capsys.readouterr().out


def test_no_merge_flag_formats_unmerged_tab_and_merge_only_skips_formatting():
    svc = Svc(merge_states()[0])
    sf.run_format(svc, "id", no_merge=True)
    svc2 = Svc(full(sheet("Utah", [HDR, [cell("s", G), cell(), cell()]])))
    sf.run_format(svc2, "id", confirm=True, merge_only=True)
    assert svc2.batches == []


def test_formatting_is_one_batch_per_tab_whatever_the_size():
    rows = [HDR] + [[cell("a"), cell("b", G), cell()] for _ in range(1500)]
    svc = Svc(full(sheet("Utah", rows)))
    sf.run_format(svc, "id", confirm=True)
    assert len(svc.batches) == 1 and len(svc.batches[0]) == 1501


def test_failed_write_prints_snapshot_path_and_restore_hint_and_exits(tmp_path, capsys):
    class Boom(Svc):
        def batchUpdate(self, spreadsheetId, body):
            raise RuntimeError("quota")
    with pytest.raises(SystemExit) as e:
        sf.run_format(Boom(full(sheet("Utah", [HDR, [cell("s", G), cell(), cell()]]))), "id", confirm=True)
    out = capsys.readouterr().out
    assert e.value.code == 1 and str(tmp_path) in out and "File > Version history" in out and "do not edit the sheet" in out


def test_rows_above_the_first_header_are_refused():
    svc = Svc(full(sheet("Utah", [[cell("note")], HDR, [cell(), cell("s", G), cell()]])))
    with pytest.raises(ValueError, match="Utah.*above the first header"):
        sf.run_format(svc, "id", confirm=True)
    assert svc.batches == []


def test_banded_ranges_over_data_are_deleted_and_reported(capsys):
    svc = Svc(full(sheet("Utah", [HDR, [cell(), cell(), cell()]], bandedRanges=[{"bandedRangeId": 5, "range": {"startRowIndex": 0, "endRowIndex": 50}}])))
    sf.run_format(svc, "id", confirm=True)
    assert {"deleteBanding": {"bandedRangeId": 5}} in svc.batches[0] and "1 banded" in capsys.readouterr().out
