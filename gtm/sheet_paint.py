"""Colour write-back: paint the sheet row of a tracked lead green or red, never over the owner's marks."""
from datetime import datetime, timezone

from gtm.sheet import QUEUE_TAB, paint_rows, read_tab, write_cells
from gtm.settings_store import setting

GREEN = {"sent", "replied", "booked"}
RED = {"rejected", "suppressed", "bounced", "unsubscribed"}


def desired_colour(status: str, owner_name: str | None, owner_email: str | None, queue_state: str | None) -> str | None:
    if status in GREEN:
        return "green"
    if status in RED:
        return "red"
    if status == "no_buyer":
        waiting = bool(owner_name) and not owner_email and queue_state != "failed"  # named, still waiting for the queue
        return None if waiting else "red"
    return None


STATUS_HEADER = "os_status"
_STATUS_OF = {"green": "sent", "red": "dropped", None: "open"}


def os_status_value(status: str, owner_name: str | None, owner_email: str | None, queue_state: str | None) -> str:
    return _STATUS_OF[desired_colour(status, owner_name, owner_email, queue_state)]


def os_col(header_cells: list[str]) -> tuple[int, bool]:
    """0-based column of the os_status header and whether it exists; else the cell right after the last header cell."""
    for i, c in enumerate(header_cells):
        if c.strip().lower() == STATUS_HEADER:
            return i, True
    return max((i for i, c in enumerate(header_cells) if c.strip()), default=-1) + 1, False


def is_ours(row_colours: list[str | None], width: int, written: str | None) -> bool:
    return bool(written) and len(row_colours) >= width and all(c == written for c in row_colours[:width])


def owner_mark(t: dict, colours: list[str | None]) -> bool:
    return not is_ours(colours, t["width"], t.get("colour_written")) and any(colours)


def plan_paint(tracked_rows: list[dict], live: dict[tuple[str, int, str], list[str | None]]) -> list[tuple[str, int, int, str | None]]:
    """tracked: tab, block, row_key, sheet_row_no, width, colour_written, desired. Returns (tab, row_no, width, colour)."""
    out = []
    for t in tracked_rows:
        colours = live.get((t["tab"], t["block"], t["row_key"]))
        if t["tab"] == QUEUE_TAB or colours is None or t.get("suppression_only"):
            continue
        written, want, width = t.get("colour_written"), t["desired"], t["width"]
        ours = is_ours(colours, width, written)
        if owner_mark(t, colours):
            continue  # the owner's mark wins
        if want == written:
            continue  # already as desired, or the owner cleared our paint and the state has not moved
        if want is None and not ours:
            continue  # nothing of ours to clear
        out.append((t["tab"], t["sheet_row_no"], width, want))
    return out


def plan_status(tracked: list[dict], live_status: dict[tuple[str, int, str], str], cols: dict[str, int]) -> list[tuple[str, int, int, str]]:
    """(tab, row_no, col, value) only where the live os_status cell differs from the desired value."""
    return [(t["tab"], t["sheet_row_no"], cols[t["tab"]], t["status_value"]) for t in tracked
            if t["tab"] in cols and live_status.get((t["tab"], t["block"], t["row_key"]), "") != t["status_value"]]


def _tracked_and_live(db, svc, sheet_id: str):
    """Returns (tracked, live colours, skipped count, live os_status cells, {tab: (header_row_no, os_col, exists)}).
    Tracked rows carry the lead's state; suppression-only rows (owner marks) take status_value from their colour.
    A tracked row is found by its row_key over the whole tab (sorting is safe); sheet_row_no is the LIVE row number
    (stored value kept as stored_row_no). A key missing or appearing twice in the tab is skipped and counted."""
    from gtm.db import fetch_all
    from gtm.sheet_import import place_key
    from gtm.sheet_map import _is_header, map_tab  # block numbers and header widths

    data = fetch_all(lambda: db.table("sheet_rows")
                     .select("id,tab,block,row_key,sheet_row_no,colour_written,colour_seen,queue_state,suppression_id,leads(status,owner_name,owner_email)")
                     .eq("orphaned", False).order("id"))
    tracked, live, moved, live_status, hdr = [], {}, 0, {}, {}
    for tab in sorted({r["tab"] for r in data} - {QUEUE_TAB}):
        rows = read_tab(svc, sheet_id, tab)
        by_no = {r.row_no: r for r in rows}
        heads = [r for r in rows if _is_header(r)]
        if heads:  # one os_status column per tab: the existing one, else right of the widest header
            found = [(r.row_no, *os_col(r.cells)) for r in heads]
            # missing: right of the longest row of the tab, so it never lands on text past the header
            hdr[tab] = next((f for f in found if f[2]), None) or (found[0][0], max(len(r.cells) for r in rows), False)
            if hdr[tab][1] >= 52:  # read_tab reads A:AZ only
                raise RuntimeError(f"{tab}: os_status column would be past AZ; move the notes columns left")
        at = {}  # row_key -> [(row_no, width)]
        for m in map_tab(tab, rows):
            try:
                at.setdefault(place_key(m), []).append((m.row_no, m.width))
            except ValueError:
                pass
        cand = []
        for r in (r for r in data if r["tab"] == tab):
            lead, here = r.get("leads"), at.get(r["row_key"], [])
            if not lead and not r.get("suppression_id"):
                continue
            if len(here) != 1:
                moved += 1  # key deleted or duplicated in the tab: never paint a guessed row
                continue
            cand.append((r, lead, *here[0]))
        claims = [c[2] for c in cand]
        for r, lead, no, width in cand:
            if claims.count(no) > 1:
                moved += 1  # two tracked records claim one live row (same key in two blocks)
                continue
            base = {**r, "stored_row_no": r["sheet_row_no"], "sheet_row_no": no, "width": width}
            colours = by_no[no].colours
            if lead:
                args = (lead["status"], lead.get("owner_name"), lead.get("owner_email"), r.get("queue_state"))
                t = {**base, "desired": desired_colour(*args), "status_value": os_status_value(*args)}
                if owner_mark(t, colours):  # the owner's colour decides, as it does for the paint
                    t["status_value"] = _STATUS_OF["red" if "red" in colours else "green"]
                tracked.append(t)
            else:  # owner mark with no lead: value follows the colour the owner applied; never repainted
                tracked.append({**base, "desired": None, "suppression_only": True,
                                "status_value": _STATUS_OF.get(r.get("colour_seen"), "open")})
            key = (tab, r["block"], r["row_key"])
            live[key] = colours
            if tab in hdr:
                cells = by_no[no].cells
                live_status[key] = cells[hdr[tab][1]] if len(cells) > hdr[tab][1] else ""
    return tracked, live, moved, live_status, hdr


def run_paint(db, svc, sheet_id: str, confirm: bool = False) -> int:
    if not setting("sheet_writeback_on", db):
        raise RuntimeError("sheet write-back is off (setting sheet_writeback_on)")
    tracked, live, moved, live_status, hdr = _tracked_and_live(db, svc, sheet_id)
    plan = plan_paint(tracked, live)
    status = plan_status(tracked, live_status, {t: h[1] for t, h in hdr.items()})
    for tab, row_no, width, colour in plan:
        print(f"{tab} row {row_no} (A..{width}): {colour or 'clear'}")
    for tab, row_no, _, value in status:
        print(f"{tab} row {row_no}: os_status {value}")
    print(f"{moved} rows moved (skipped)")
    print(f"{len(plan)} rows" + ("" if confirm else " (preview; --confirm to paint)"))
    print(f"{len(status)} status cells")
    if confirm:  # follow the owner's sort: keep the stored row number current
        for t in tracked:
            if t.get("stored_row_no", t["sheet_row_no"]) != t["sheet_row_no"]:
                db.table("sheet_rows").update({"sheet_row_no": t["sheet_row_no"]}).eq("id", t["id"]).execute()
    if not confirm:
        return len(plan)
    for tab in sorted({s[0] for s in status}):
        head = [] if hdr[tab][2] else [(hdr[tab][0], hdr[tab][1], STATUS_HEADER)]  # header once, when missing
        write_cells(svc, sheet_id, tab, head + [(n, c, v) for t, n, c, v in status if t == tab])
    ids = {(t["tab"], t["sheet_row_no"]): t["id"] for t in tracked}
    for tab in sorted({p[0] for p in plan}):
        cells = [(n, w, c) for t, n, w, c in plan if t == tab]
        paint_rows(svc, sheet_id, tab, cells)
        # record right after the paint; a crash between the two leaves a paint that reads as an owner mark (accepted ceiling)
        now = datetime.now(timezone.utc).isoformat()
        for n, _, c in cells:
            db.table("sheet_rows").update({"colour_written": c, "colour_seen": c or "none", "written_at": now}).eq("id", ids[(tab, n)]).execute()
    return len(plan)
