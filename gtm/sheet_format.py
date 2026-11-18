"""sheet-format: normalise the leads sheet to the standard in docs/SHEET-GUIDELINES.md.
Marks (pure green = sent, pure red = dropped) keep their meaning: partial marks widen to the whole row, nothing else is a mark.
Read-only unless confirm. Never touches the Queue tab. Prints counts only, never lead data.
Step F (merge blocks) is its own run; steps A-E (formatting) run on the next call."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from gtm.sheet import PURE, QUEUE_TAB, SECRETS, colour_of
from gtm.sheet_map import MERGE_ALIAS, MERGE_TARGET, TAB_STATE

HEADER_FILL = {"red": 0.2, "green": 0.2, "blue": 0.2}
WHITE = {"red": 1, "green": 1, "blue": 1}
MAX_REQUESTS = 10000  # one batchUpdate per tab; a tab splits only above this (payload size is the real limit)
END = 10**9
_FIELDS = ("sheets(properties(sheetId,title,gridProperties(columnCount)),conditionalFormats(ranges),tables(tableId,name,range),"
           "merges,basicFilter(range),filterViews(filterViewId,range),bandedRanges(bandedRangeId,range),"
           "data(startRow,rowData(values(formattedValue,userEnteredFormat(backgroundColor)))))")
RESTORE = "Restore from the xlsx backup or File > Version history."


def _is_white(bg: dict) -> bool:
    return all(abs(bg.get(c, 0) - 1) <= 0.02 for c in ("red", "green", "blue"))


def get_sheet(svc, sheet_id: str) -> dict:
    return svc.spreadsheets().get(spreadsheetId=sheet_id, includeGridData=True, fields=_FIELDS).execute()


def _span(r: dict) -> tuple[int, int]:
    return (r.get("startRowIndex", 0), r.get("endRowIndex", END))


def read_grid(resp: dict, tabs: list[str]) -> dict[str, dict]:
    """tab -> {gid, cols, rows: [(row_no, [(text, bg)...])] non-blank only, cf, tables, table_spans, merges, filters, banded}.
    Spans are (start, end) 0-based row indexes, end exclusive."""
    out = {}
    for s in resp.get("sheets", []):
        title = s["properties"]["title"]
        if title not in tabs or title == QUEUE_TAB:
            continue
        rows = []
        for d in s.get("data", []):
            for i, row in enumerate(d.get("rowData", [])):
                cells = [(str(v.get("formattedValue", "")), v.get("userEnteredFormat", {}).get("backgroundColor") or {}) for v in row.get("values", [])]
                if any(t.strip() for t, _ in cells):
                    rows.append((d.get("startRow", 0) + i + 1, cells))
        out[title] = {
            "gid": s["properties"]["sheetId"], "cols": s["properties"].get("gridProperties", {}).get("columnCount", 26), "rows": rows,
            "cf": [[_span(r) for r in c.get("ranges", [])] for c in s.get("conditionalFormats", [])],
            "tables": [t.get("name", "?") for t in s.get("tables", [])], "table_spans": [_span(t.get("range", {})) for t in s.get("tables", [])],
            "merges": [_span(r) for r in s.get("merges", [])],
            "filters": ([_span(s["basicFilter"].get("range", {}))] if "basicFilter" in s else []) + [_span(f.get("range", {})) for f in s.get("filterViews", [])],
            "banded": [(b["bandedRangeId"], _span(b.get("range", {}))) for b in s.get("bandedRanges", [])]}
    return out


def _width(cells) -> int:
    return max((i + 1 for i, (t, _) in enumerate(cells) if t.strip()), default=0)


def _is_header(cells) -> bool:
    return bool(cells) and cells[0][0].strip().lower() in ("business", "company")


def row_mark(cells) -> str | None:
    cols = {colour_of(bg) for _, bg in cells}
    return "red" if "red" in cols else "green" if "green" in cols else None


def marks_of(grid: dict[str, dict]) -> dict[tuple[str, int], str]:
    """(tab, row_no) -> colour for every data row with a pure mark (header rows and rows before any header excluded)."""
    out = {}
    for tab, g in grid.items():
        seen = False
        for no, cells in g["rows"]:
            if _is_header(cells):
                seen = True
            elif seen and (m := row_mark(cells)):
                out[(tab, no)] = m
    return out


def _rng(gid, row, width):
    return {"sheetId": gid, "startRowIndex": row - 1, "endRowIndex": row, "startColumnIndex": 0, "endColumnIndex": width}


def _rows_txt(s: int, e: int) -> str:
    return f"{s + 1}-{'end' if e >= END else e}"


def blockers(tab: str, g: dict, from_row: int, merge: bool) -> list[str]:
    """Things a write cannot safely cross, at rows >= from_row: merged cells, filters (any, when merging) and Tables (when merging)."""
    out = [f"{tab}: merged cells at rows {_rows_txt(s, e)}" for s, e in g["merges"] if e > from_row - 1]
    out += [f"{tab}: filter at rows {_rows_txt(s, e)}" for s, e in g["filters"] if merge or e > from_row - 1]
    if merge:
        out += [f"{tab}: Table {n} (Format > Convert to range first)" for n in g["tables"]]
    return out


def plan_tab(tab: str, g: dict) -> tuple[list[dict], dict[str, int]]:
    """(requests, counts) that normalise one tab (steps A-E)."""
    gid, reqs = g["gid"], []
    n = {"marked": 0, "cleared": 0, "headers": 0, "cf_deleted": 0, "tables": len(g["tables"]), "banded": 0}
    width, data_rows = 0, []
    for no, cells in g["rows"]:
        if _is_header(cells):
            width = _width(cells)
            n["headers"] += 1
            reqs.append({"repeatCell": {"range": _rng(gid, no, width), "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_FILL, "textFormat": {"foregroundColor": WHITE, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat.foregroundColor,textFormat.bold)"}})
            continue
        data_rows.append(no)
        w = max(width, len(cells))
        m = row_mark(cells)
        if m:
            if any(colour_of(bg) != m for _, bg in cells[:width]) or len(cells) < width:  # partial or mixed: widen to the whole row
                n["marked"] += 1
                reqs.append({"repeatCell": {"range": _rng(gid, no, width), "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0, "green": 0, "blue": 0, **PURE[m]}}}, "fields": "userEnteredFormat.backgroundColor"}})
            # a mixed row's cells beyond the header width that are not pure stay untouched (outside the standard's columns)
        elif any(bg and not _is_white(bg) for _, bg in cells):
            n["cleared"] += 1
            reqs.append({"repeatCell": {"range": _rng(gid, no, w), "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat.backgroundColor"}})
    bad = [i for i, ranges in enumerate(g["cf"]) if any(any(s < r <= e for r in data_rows) for s, e in ranges)]
    n["cf_total"], n["cf_deleted"] = len(g["cf"]), len(bad)
    banded = [i for i, (s, e) in g["banded"] if any(s < r <= e for r in data_rows)]
    n["banded"] = len(banded)
    return [{"deleteConditionalFormatRule": {"sheetId": gid, "index": i}} for i in sorted(bad, reverse=True)] + \
           [{"deleteBanding": {"bandedRangeId": i}} for i in banded] + reqs, n


def _snapshot(marks: dict) -> str:
    SECRETS.mkdir(exist_ok=True)
    p = SECRETS / f"sheet_marks_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps([{"tab": t, "row_no": r, "mark": m} for (t, r), m in sorted(marks.items())]))
    return str(p)


def _sig(cells) -> list[tuple[str, str | None]]:
    """(text, pure colour) per cell, trailing empties trimmed: format-only noise never differs."""
    sig = [(t, colour_of(bg)) for t, bg in cells]
    while sig and sig[-1] == ("", None):
        sig.pop()
    return sig


def plan_merge(tab: str, g: dict) -> dict | None:
    """None for a one-block tab. Else the requests folding every later block under block 1 in the tab's MERGE_TARGET header,
    and the exact rows (text, pure colour) expected afterwards. Raises ValueError (before any write) for a header with no unique
    target column, text past a header's width, or a pure mark past a later block's header width.
    Bottom block first, so rows above it never move. Per block: delete the gap and header rows, cut each moving column to a staging
    area right of the used width, cut it from there to its target column, then write the unified header row.
    cutPaste PASTE_NORMAL keeps values, links, notes, formats and marks."""
    rows = g["rows"]
    hdrs = [i for i, (_, c) in enumerate(rows) if _is_header(c)]
    if len(hdrs) < 2:
        return None
    target = MERGE_TARGET[tab]
    blks = [(rows[h], rows[h + 1:(hdrs[k + 1] if k + 1 < len(hdrs) else len(rows))]) for k, h in enumerate(hdrs)]
    (h1_no, h1), data1 = blks[0]
    names1 = [t.strip().lower() for t, _ in h1[:_width(h1)]]
    if names1 != target[:len(names1)]:
        raise ValueError(f"{tab!r}: block 1 header must be the start of the target header")
    for no, c in data1:
        if _width(c) > len(names1):
            raise ValueError(f"{tab!r}: text beyond the header at row {no}")
    width = max(len(target), max((len(c) for _, c in rows), default=0))  # staging starts here
    maps = [{}]  # per block: source column -> target column
    for (_, hc), data in blks[1:]:
        m, hw = {}, _width(hc)
        for i, (t, _) in enumerate(hc[:hw]):
            name = t.strip().lower()
            dst = MERGE_ALIAS.get(name, name if name in target else None)
            if dst is None or target.index(dst) in m.values():
                raise ValueError(f"{tab!r}: a block header has no unique target column")
            m[i] = target.index(dst)
        for no, c in data:
            if _width(c) > hw:
                raise ValueError(f"{tab!r}: text beyond the header at row {no}")
            if any(colour_of(bg) for _, bg in c[hw:]):
                raise ValueError(f"mark outside the header width at {tab} row {no}")
        maps.append(m)
    last = [(b[-1][0] if b else hd[0]) for hd, b in blks]  # last row of each block
    gid, nstage = g["gid"], max(sum(c != t for c, t in m.items()) for m in maps)
    append = max(0, width + nstage - g["cols"])
    reqs = [{"appendDimension": {"sheetId": gid, "dimension": "COLUMNS", "length": append}}] if append else []
    for k in range(len(blks) - 1, 0, -1):
        h_no, n, start = blks[k][0][0], last[k] - blks[k][0][0], last[k - 1]
        reqs.append({"deleteDimension": {"range": {"sheetId": gid, "dimension": "ROWS", "startIndex": start, "endIndex": h_no}}})
        moving = [(c, t) for c, t in sorted(maps[k].items()) if c != t]
        col = lambda c: {"sheetId": gid, "startRowIndex": start, "endRowIndex": start + n, "startColumnIndex": c, "endColumnIndex": c + 1}
        for src, dst in ([(c, width + j) for j, (c, _) in enumerate(moving)] + [(width + j, t) for j, (_, t) in enumerate(moving)]) if n else []:
            reqs.append({"cutPaste": {"source": col(src), "destination": {"sheetId": gid, "rowIndex": start, "columnIndex": dst}, "pasteType": "PASTE_NORMAL"}})
    reqs.append({"updateCells": {"start": {"sheetId": gid, "rowIndex": h1_no - 1, "columnIndex": 0}, "fields": "userEnteredValue",
                                 "rows": [{"values": [{"userEnteredValue": {"stringValue": n}} for n in target]}]}})
    keep = max(g["cols"], width)  # never delete a real target column: only the staging columns this run appended beyond it
    if g["cols"] + append > keep:
        reqs.append({"deleteDimension": {"range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": keep, "endIndex": g["cols"] + append}}})
    expected, marks = {h1_no: [(n, None) for n in target], **{no: _sig(c) for no, c in data1}}, {}
    shift, merged = 0, []
    for k in range(1, len(blks)):
        shift += blks[k][0][0] - last[k - 1]
        hw = _width(blks[k][0][1])
        for no, c in blks[k][1]:
            new = [("", None)] * len(target)
            for i, cell_ in enumerate(_sig(c[:hw])):
                new[maps[k][i]] = cell_
            while new and new[-1] == ("", None):
                new.pop()
            expected[no - shift], marks[no - shift] = new, row_mark(c)
        merged.append({"block": k + 1, "first": blks[k][0][0], "last": last[k]})
    return {"tab": tab, "n": len(blks), "merged": merged, "requests": reqs, "expected": expected, "marks": marks, "added": target[len(names1):]}


def _merge_snapshot(tab: str, g: dict) -> str:
    SECRETS.mkdir(exist_ok=True)
    p = SECRETS / f"sheet_merge_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps({"tab": tab, "rows": [{"row": no, "cells": [t for t, _ in c], "marks": [colour_of(bg) for _, bg in c]} for no, c in g["rows"]]}))
    return str(p)


def _send(svc, sheet_id: str, reqs: list[dict], snap: str) -> None:
    try:
        svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs}).execute()
    except Exception as e:  # nothing is known about how much applied: stop and point at the way back
        print(f"FAIL: write failed ({type(e).__name__}). Snapshot: {snap}. {RESTORE}")
        sys.exit(1)


def run_format(svc, sheet_id: str, confirm: bool = False, tab: str | None = None, merge_only: bool = False, no_merge: bool = False) -> dict:
    tabs = [t for t in TAB_STATE if t == (tab or t) and t != QUEUE_TAB]
    if not tabs:
        raise ValueError(f"tab {tab!r} is not a lead tab")
    if confirm:
        print("sheet-format --confirm: do not edit the sheet during the run; worker sheet jobs must be off.")
    grid = read_grid(get_sheet(svc, sheet_id), tabs)
    blocked, merges = [], []
    for t, g in grid.items():
        hdrs = [i for i, (_, c) in enumerate(g["rows"]) if _is_header(c)]
        if g["rows"] and (not hdrs or hdrs[0] > 0):
            blocked.append(f"{t}: non-blank rows above the first header (row {g['rows'][0][0]})")
            continue
        if len(hdrs) > 1 and not no_merge:
            if t not in MERGE_TARGET:
                print(f"{t}: {len(hdrs)} blocks, needs a target header; left alone")
                continue
            try:
                merges.append(plan_merge(t, g))
            except ValueError as e:
                blocked.append(str(e))
                continue
            blocked += blockers(t, g, g["rows"][hdrs[1]][0], merge=True)
    if not merges and not merge_only:
        for t, g in grid.items():
            if g["rows"]:
                blocked += blockers(t, g, g["rows"][0][0], merge=False)
    if blocked:
        for b in blocked:
            print("BLOCKED:", b)
        raise ValueError("; ".join(blocked))
    # Step F: fold every later block under block 1 (its own batchUpdate per tab, re-read, verified cell by cell); then stop
    if merges:
        for m in merges:
            for b in m["merged"]:
                print(f"{m['tab']}: {m['n']} blocks -> 1: block {b['block']} rows {b['first']}-{b['last']} ({b['last'] - b['first'] + 1} rows) "
                      f"{'merging' if confirm else 'merged'} under block 1; columns added: {', '.join(m['added'])}")
        if not confirm:
            print("formatting steps are planned after the merge: rerun" + ("" if merge_only else " (without --confirm this is a dry run: nothing written)"))
            return {}
        snaps = {}
        for m in merges:
            snaps[m["tab"]] = _merge_snapshot(m["tab"], grid[m["tab"]])
            print("merge snapshot:", snaps[m["tab"]])
            _send(svc, sheet_id, m["requests"], snaps[m["tab"]])
        new = read_grid(get_sheet(svc, sheet_id), tabs)
        for m in merges:
            rows = new[m["tab"]]["rows"]
            if {no: _sig(c) for no, c in rows} != m["expected"] or {no: row_mark(c) for no, c in rows if no in m["marks"]} != m["marks"]:
                print(f"FAIL: merge of {m['tab']} changed values or marks. Snapshot: {snaps[m['tab']]}. {RESTORE}")
                sys.exit(1)
        print("verified: merge rows and marks match")
        print("merge done and verified; run sheet-format again for the formatting steps")
        return {}
    if merge_only:
        print("no merge needed")
        return {}
    before, report, per_tab = marks_of(grid), {}, {}
    for t, g in grid.items():
        r, n = plan_tab(t, g)
        per_tab[t], report[t] = r, n
        print(f"{t}: {n['marked']} rows widened to full-row marks, {n['cleared']} rows cleared of tints, {n['headers']} header rows styled, "
              f"{n['cf_deleted']} of {n['cf_total']} conditional rules deleted, {n['banded']} banded ranges deleted, {n['tables']} tables")
        for name in g["tables"]:
            print(f"  table {name}: manual step, Format > Convert to range (the API deleteTable is not used: its effect on the data is undocumented)")
    print(f"marks: {sum(m == 'green' for m in before.values())} green, {sum(m == 'red' for m in before.values())} red; "
          f"{sum(len(r) for r in per_tab.values())} requests")
    if not confirm:
        print("Dry run: nothing written. Rerun with --confirm.")
        return report
    snap = _snapshot(before)
    print("snapshot:", snap)
    for t, reqs in per_tab.items():
        for i in range(0, len(reqs), MAX_REQUESTS):
            _send(svc, sheet_id, reqs[i:i + MAX_REQUESTS], snap)
            after = marks_of(read_grid(get_sheet(svc, sheet_id), [t]))
            if after != {k: v for k, v in before.items() if k[0] == t}:
                print(f"FAIL: marks changed on {t} ({len(set(before.items()) - set(after.items()))} lost or recoloured). Snapshot: {snap}. {RESTORE}")
                sys.exit(1)
    print(f"verified: {len(before)} marked rows unchanged")
    return report
