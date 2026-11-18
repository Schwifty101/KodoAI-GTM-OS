"""sheet-format: normalise the leads sheet to the standard in docs/SHEET-GUIDELINES.md.
Marks (pure green = sent, pure red = dropped) keep their meaning: partial marks widen to the whole row, nothing else is a mark.
Read-only unless confirm. Never touches the Queue tab. Prints counts only, never lead data."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from gtm.sheet import PURE, QUEUE_TAB, SECRETS, colour_of
from gtm.sheet_map import TAB_STATE

HEADER_FILL = {"red": 0.2, "green": 0.2, "blue": 0.2}
WHITE = {"red": 1, "green": 1, "blue": 1}
CHUNK = 400  # requests per batchUpdate, well under the request size limit
_FIELDS = ("sheets(properties(sheetId,title),conditionalFormats(ranges),tables(tableId,name),"
           "data(startRow,rowData(values(formattedValue,userEnteredFormat(backgroundColor)))))")


def _is_white(bg: dict) -> bool:
    return all(abs(bg.get(c, 0) - 1) <= 0.02 for c in ("red", "green", "blue"))


def read_grid(svc, sheet_id: str, tabs: list[str]) -> dict[str, dict]:
    """tab -> {gid, rows: [(row_no, [(text, bg)...])] non-blank only, cf: [row ranges], tables: [names]}."""
    resp = svc.spreadsheets().get(spreadsheetId=sheet_id, includeGridData=True, fields=_FIELDS).execute()
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
        out[title] = {"gid": s["properties"]["sheetId"], "rows": rows, "cf": cf, "tables": [t.get("name", "?") for t in s.get("tables", [])]}
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


def run_format(svc, sheet_id: str, confirm: bool = False, tab: str | None = None) -> dict:
    tabs = [t for t in TAB_STATE if t == (tab or t) and t != QUEUE_TAB]
    if not tabs:
        raise ValueError(f"tab {tab!r} is not a lead tab")
    grid = read_grid(svc, sheet_id, tabs)
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
    after = marks_of(read_grid(svc, sheet_id, tabs))
    if after != before:
        print(f"FAIL: marks changed ({len(set(before.items()) - set(after.items()))} lost or recoloured). Restore from the snapshot (tab, row, colour).")
        sys.exit(1)
    print(f"verified: {len(after)} marked rows unchanged")
    return report
