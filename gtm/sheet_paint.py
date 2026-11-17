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
    """Tracked sheet_rows (with the lead's state) and the live colours of each row, read from the sheet."""
    from gtm.sheet_map import map_tab  # Task 4: block numbers and header widths

    data = (db.table("sheet_rows")
            .select("id,tab,block,row_key,sheet_row_no,colour_written,queue_state,leads(status,owner_name,owner_email)")
            .not_.is_("lead_id", "null").eq("orphaned", False).execute().data)
    tracked, live = [], {}
    for tab in sorted({r["tab"] for r in data} - {QUEUE_TAB}):
        rows = read_tab(svc, sheet_id, tab)
        by_no = {r.row_no: r for r in rows}
        width = {(m.block, m.row_no): m.width for m in map_tab(tab, rows)}
        for r in (r for r in data if r["tab"] == tab):
            w, lead = width.get((r["block"], r["sheet_row_no"])), r.get("leads")
            if w is None or not lead or r["sheet_row_no"] not in by_no:
                continue  # row moved or gone: the importer's job, not ours
            tracked.append({**r, "width": w, "desired": desired_colour(
                lead["status"], lead.get("owner_name"), lead.get("owner_email"), r.get("queue_state"))})
            live[(tab, r["block"], r["row_key"])] = by_no[r["sheet_row_no"]].colours
    return tracked, live


def run_paint(db, svc, sheet_id: str, confirm: bool = False) -> int:
    if not setting("sheet_writeback_on", db):
        raise RuntimeError("sheet write-back is off (setting sheet_writeback_on)")
    tracked, live = _tracked_and_live(db, svc, sheet_id)
    plan = plan_paint(tracked, live)
    for tab, row_no, width, colour in plan:
        print(f"{tab} row {row_no} (A..{width}): {colour or 'clear'}")
    print(f"{len(plan)} rows" + ("" if confirm else " (preview; --confirm to paint)"))
    if not confirm or not plan:
        return len(plan)
    for tab in sorted({p[0] for p in plan}):
        paint_rows(svc, sheet_id, tab, [(n, w, c) for t, n, w, c in plan if t == tab])
    ids = {(t["tab"], t["sheet_row_no"]): t["id"] for t in tracked}
    now = datetime.now(timezone.utc).isoformat()
    for tab, row_no, _, colour in plan:
        db.table("sheet_rows").update({"colour_written": colour, "written_at": now}).eq("id", ids[(tab, row_no)]).execute()
    return len(plan)
