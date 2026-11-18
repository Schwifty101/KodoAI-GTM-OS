"""sheet-format: normalise the leads sheet to the standard in docs/SHEET-GUIDELINES.md.
Marks (pure green = sent, pure red = dropped) keep their meaning: partial marks widen to the whole row, nothing else is a mark.
Read-only unless confirm. Never touches the Queue tab. Prints counts only, never lead data."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from gtm.sheet import PURE, QUEUE_TAB, SECRETS, colour_of
from gtm.sheet_map import MERGE_ALIAS, MERGE_TARGET, TAB_STATE

HEADER_FILL = {"red": 0.2, "green": 0.2, "blue": 0.2}
WHITE = {"red": 1, "green": 1, "blue": 1}
CHUNK = 400  # requests per batchUpdate, well under the request size limit
_FIELDS = ("sheets(properties(sheetId,title,gridProperties(columnCount)),conditionalFormats(ranges),tables(tableId,name),"
           "data(startRow,rowData(values(formattedValue,userEnteredFormat(backgroundColor)))))")


def _is_white(bg: dict) -> bool:
    return all(abs(bg.get(c, 0) - 1) <= 0.02 for c in ("red", "green", "blue"))


def get_sheet(svc, sheet_id: str) -> dict:
    return svc.spreadsheets().get(spreadsheetId=sheet_id, includeGridData=True, fields=_FIELDS).execute()


def read_grid(resp: dict, tabs: list[str]) -> dict[str, dict]:
    """tab -> {gid, cols, rows: [(row_no, [(text, bg)...])] non-blank only, cf: [row ranges], tables: [names]}."""
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
        cf = [[(r.get("startRowIndex", 0), r.get("endRowIndex", 10**9)) for r in c.get("ranges", [])] for c in s.get("conditionalFormats", [])]
        out[title] = {"gid": s["properties"]["sheetId"], "cols": s["properties"].get("gridProperties", {}).get("columnCount", 26), "rows": rows, "cf": cf, "tables": [t.get("name", "?") for t in s.get("tables", [])]}
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
    out, seen = {}, False
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


def plan_tab(tab: str, g: dict) -> tuple[list[dict], dict[str, int]]:
    """(requests, counts) that normalise one tab."""
    gid, reqs = g["gid"], []
    n = {"marked": 0, "cleared": 0, "headers": 0, "cf_deleted": 0, "tables": len(g["tables"])}
    width, data_rows = 0, []
    for no, cells in g["rows"]:
        if _is_header(cells):
            width = _width(cells)
            n["headers"] += 1
            reqs.append({"repeatCell": {"range": _rng(gid, no, width), "cell": {"userEnteredFormat": {
                "backgroundColor": HEADER_FILL, "textFormat": {"foregroundColor": WHITE, "bold": True}}},
                "fields": "userEnteredFormat(backgroundColor,textFormat.foregroundColor,textFormat.bold)"}})
            continue
        if not width:
            continue  # before any header: not ours
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
    n["cf_total"] = len(g["cf"])
    n["cf_deleted"] = len(bad)
    cf_reqs = [{"deleteConditionalFormatRule": {"sheetId": gid, "index": i}} for i in sorted(bad, reverse=True)]
    return cf_reqs + reqs, n


def _snapshot(marks: dict) -> str:
    SECRETS.mkdir(exist_ok=True)
    p = SECRETS / f"sheet_marks_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps([{"tab": t, "row_no": r, "mark": m} for (t, r), m in sorted(marks.items())]))
    return p.name


def _sig(cells) -> list[tuple[str, str | None]]:
    """(text, pure colour) per cell, trailing empties trimmed: format-only noise never differs."""
    sig = [(t, colour_of(bg)) for t, bg in cells]
    while sig and sig[-1] == ("", None):
        sig.pop()
    return sig


def plan_merge(tab: str, g: dict) -> dict | None:
    """None for a one-block tab. Else the requests folding every later block under block 1 in the tab's MERGE_TARGET header,
    and the exact rows (text, pure colour) expected afterwards. Raises ValueError for a header with no unique target column
    or a data row with content beyond its header. Bottom block first, so rows above it never move.
    Per block: delete the gap and header rows, cut each moving column to a staging area right of the used width, cut it from
    there to its target column, then write the unified header row. cutPaste PASTE_NORMAL keeps values, links, formats, marks."""
    rows = g["rows"]
    hdrs = [i for i, (_, c) in enumerate(rows) if _is_header(c)]
    if len(hdrs) < 2:
        return None
    target = MERGE_TARGET[tab]
    blks = [(rows[h], rows[h + 1:(hdrs[k + 1] if k + 1 < len(hdrs) else len(rows))]) for k, h in enumerate(hdrs)]
    (h1_no, h1), _ = blks[0]
    names1 = [t.strip().lower() for t, _ in h1[:_width(h1)]]
    if names1 != target[:len(names1)]:
        raise ValueError(f"{tab!r}: block 1 header must be the start of the target header")
    width = max(len(target), max((len(c) for _, c in rows), default=0))  # staging starts here
    maps = [{}]  # per block: source column -> target column
    for (_, hc), data in blks[1:]:
        m = {}
        for i, (t, _) in enumerate(hc[:_width(hc)]):
            name = t.strip().lower()
            dst = MERGE_ALIAS.get(name, name if name in target else None)
            if dst is None or target.index(dst) in m.values():
                raise ValueError(f"{tab!r}: a block header has no unique target column")
            m[i] = target.index(dst)
        if any(_width(c) > _width(hc) for _, c in data):
            raise ValueError(f"{tab!r}: a data row has content beyond its header")
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
    if append:
        reqs.append({"deleteDimension": {"range": {"sheetId": gid, "dimension": "COLUMNS", "startIndex": g["cols"], "endIndex": g["cols"] + append}}})
    expected = {h1_no: [(n, None) for n in target], **{no: _sig(c) for no, c in blks[0][1]}}
    shift, merged = 0, []
    for k in range(1, len(blks)):
        shift += blks[k][0][0] - last[k - 1]
        for no, c in blks[k][1]:
            new = [("", None)] * len(target)
            for i, cell_ in enumerate(_sig(c)):
                new[maps[k][i]] = cell_
            while new and new[-1] == ("", None):
                new.pop()
            expected[no - shift] = new
        merged.append({"block": k + 1, "first": blks[k][0][0], "last": last[k]})
    return {"tab": tab, "n": len(blks), "merged": merged, "requests": reqs, "expected": expected, "added": target[len(names1):]}


def _merge_snapshot(tab: str, g: dict) -> str:
    SECRETS.mkdir(exist_ok=True)
    p = SECRETS / f"sheet_merge_snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    p.write_text(json.dumps({"tab": tab, "rows": [{"row": no, "cells": [t for t, _ in c], "marks": [colour_of(bg) for _, bg in c]} for no, c in g["rows"]]}))
    return p.name


def run_format(svc, sheet_id: str, confirm: bool = False, tab: str | None = None) -> dict:
    tabs = [t for t in TAB_STATE if t == (tab or t) and t != QUEUE_TAB]
    if not tabs:
        raise ValueError(f"tab {tab!r} is not a lead tab")
    grid = read_grid(get_sheet(svc, sheet_id), tabs)
    # Step F: fold every later block under block 1 (its own batchUpdate, re-read, verified cell by cell), before steps A-E
    merges = []
    for t, g in grid.items():
        n_blocks = sum(1 for _, c in g["rows"] if _is_header(c))
        if n_blocks > 1 and t not in MERGE_TARGET:
            print(f"{t}: {n_blocks} blocks, needs a target header; left alone")
        elif m := plan_merge(t, g):
            merges.append(m)
            for b in m["merged"]:
                print(f"{t}: {m['n']} blocks -> 1: block {b['block']} rows {b['first']}-{b['last']} ({b['last'] - b['first'] + 1} rows) "
                      f"{'merging' if confirm else 'merged'} under block 1; columns added: {', '.join(m['added'])}")
    if merges and confirm:
        for m in merges:
            print("merge snapshot:", _merge_snapshot(m["tab"], grid[m["tab"]]))
            for i in range(0, len(m["requests"]), CHUNK):
                svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": m["requests"][i:i + CHUNK]}).execute()
        grid = read_grid(get_sheet(svc, sheet_id), tabs)
        for m in merges:
            if {no: _sig(c) for no, c in grid[m["tab"]]["rows"]} != m["expected"]:
                print(f"FAIL: merge of {m['tab']} changed values or marks. Restore from the xlsx backup (the merge snapshot lists the old rows).")
                sys.exit(1)
        print("verified: merge rows and marks match")
    before, reqs, report = marks_of(grid), [], {}
    for t, g in grid.items():
        r, n = plan_tab(t, g)
        reqs += r
        report[t] = n
        print(f"{t}: {n['marked']} rows widened to full-row marks, {n['cleared']} rows cleared of tints, {n['headers']} header rows styled, "
              f"{n['cf_deleted']} of {n['cf_total']} conditional rules deleted, {n['tables']} tables")
        for name in g["tables"]:
            print(f"  table {name}: manual step, Format > Convert to range (the API deleteTable is not used: its effect on the data is undocumented)")
    print(f"marks: {sum(m == 'green' for m in before.values())} green, {sum(m == 'red' for m in before.values())} red; {len(reqs)} requests")
    if not confirm:
        print("Dry run: nothing written. Rerun with --confirm.")
        return report
    print("snapshot:", _snapshot(before))
    for i in range(0, len(reqs), CHUNK):
        svc.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body={"requests": reqs[i:i + CHUNK]}).execute()
    after = marks_of(read_grid(get_sheet(svc, sheet_id), tabs))
    if after != before:
        print(f"FAIL: marks changed ({len(set(before.items()) - set(after.items()))} lost or recoloured). Restore from the snapshot (tab, row, colour).")
        sys.exit(1)
    print(f"verified: {len(after)} marked rows unchanged")
    return report
