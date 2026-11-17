"""Colour write-back: paint the sheet row of a tracked lead green or red, never over the owner's marks."""
from datetime import datetime, timezone

from gtm.sheet import QUEUE_TAB, paint_rows, read_tab
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


def is_ours(row_colours: list[str | None], width: int, written: str | None) -> bool:
    return bool(written) and len(row_colours) >= width and all(c == written for c in row_colours[:width])


def plan_paint(tracked_rows: list[dict], live: dict[tuple[str, int, str], list[str | None]]) -> list[tuple[str, int, int, str | None]]:
    """tracked: tab, block, row_key, sheet_row_no, width, colour_written, desired. Returns (tab, row_no, width, colour)."""
    out = []
    for t in tracked_rows:
        colours = live.get((t["tab"], t["block"], t["row_key"]))
        if t["tab"] == QUEUE_TAB or colours is None:
            continue
        written, want, width = t.get("colour_written"), t["desired"], t["width"]
        ours = is_ours(colours, width, written)
        if not ours and any(colours):
            continue  # the owner's mark wins
        if want == written:
            continue  # already as desired, or the owner cleared our paint and the state has not moved
        if want is None and not ours:
            continue  # nothing of ours to clear
        out.append((t["tab"], t["sheet_row_no"], width, want))
    return out


def _tracked_and_live(db, svc, sheet_id: str):
    """Tracked sheet_rows (with the lead's state), the live colours of each row, and the count of moved rows.
    A tracked row is painted only if the live row at its stored (block, row_no) still has its row_key."""
    from gtm.db import fetch_all
    from gtm.sheet_import import place_key
    from gtm.sheet_map import map_tab  # block numbers and header widths

    data = fetch_all(lambda: db.table("sheet_rows")
                     .select("id,tab,block,row_key,sheet_row_no,colour_written,queue_state,leads(status,owner_name,owner_email)")
                     .not_.is_("lead_id", "null").eq("orphaned", False).order("id"))
    tracked, live, moved = [], {}, 0
    for tab in sorted({r["tab"] for r in data} - {QUEUE_TAB}):
        rows = read_tab(svc, sheet_id, tab)
        by_no = {r.row_no: r for r in rows}
        at = {}  # (block, row_no) -> (row_key, width)
        for m in map_tab(tab, rows):
            try:
                at[(m.block, m.row_no)] = (place_key(m), m.width)
            except ValueError:
                pass
        for r in (r for r in data if r["tab"] == tab):
            lead, here = r.get("leads"), at.get((r["block"], r["sheet_row_no"]))
            if not lead:
                continue
            if not here or here[0] != r["row_key"]:
                moved += 1  # sorted, inserted or deleted since the last import: never paint another lead's row
                continue
            tracked.append({**r, "width": here[1], "desired": desired_colour(
                lead["status"], lead.get("owner_name"), lead.get("owner_email"), r.get("queue_state"))})
            live[(tab, r["block"], r["row_key"])] = by_no[r["sheet_row_no"]].colours
    return tracked, live, moved


def run_paint(db, svc, sheet_id: str, confirm: bool = False) -> int:
    if not setting("sheet_writeback_on", db):
        raise RuntimeError("sheet write-back is off (setting sheet_writeback_on)")
    tracked, live, moved = _tracked_and_live(db, svc, sheet_id)
    plan = plan_paint(tracked, live)
    for tab, row_no, width, colour in plan:
        print(f"{tab} row {row_no} (A..{width}): {colour or 'clear'}")
    print(f"{moved} rows moved (skipped)")
    print(f"{len(plan)} rows" + ("" if confirm else " (preview; --confirm to paint)"))
    if not confirm or not plan:
        return len(plan)
    ids = {(t["tab"], t["sheet_row_no"]): t["id"] for t in tracked}
    for tab in sorted({p[0] for p in plan}):
        cells = [(n, w, c) for t, n, w, c in plan if t == tab]
        paint_rows(svc, sheet_id, tab, cells)
        # record right after the paint; a crash between the two leaves a paint that reads as an owner mark (accepted ceiling)
        now = datetime.now(timezone.utc).isoformat()
        for n, _, c in cells:
            db.table("sheet_rows").update({"colour_written": c, "written_at": now}).eq("id", ids[(tab, n)]).execute()
    return len(plan)
