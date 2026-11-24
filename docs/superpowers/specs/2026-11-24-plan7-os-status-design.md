# Plan 7 design: `os_status` column, daily paint, sort-safe rows (2026-11-24)

Owner decisions (2026-11-24): Option A (the sheet mirrors only rows it already tracks; new scraped leads never go to the sheet; batches live in the OS), add `os_status`, keep the queue automatic. UI run-now buttons are a separate plan (Plan 8).

## 1. Problem
- Sheets cannot sort by colour live, so green, red and uncoloured rows cannot be grouped automatically.
- `sheet-paint` is not scheduled; only `sheet-queue` is (`gtm/schedule.py` `queue_tick`).
- Sorting a data tab today makes paint skip every moved row (`_tracked_and_live` in `gtm/sheet_paint.py` matches by stored `sheet_row_no` and counts a key mismatch as "moved"), so sorting would silently freeze the colours. Found while writing this spec; earlier advice that sorting is safe was only true for the importer.

## 2. Design
1. **`os_status` column.** One text column per data tab (Texas, Newyork, Utah), OS-owned, header `os_status`. Found by header name; if missing it is added in the first empty header cell right of the last header cell (Newyork has notes in O..Z, so it lands after them). Never inside a tracked width A..J paint range. Plain text, no formatting; the owner sorts or filters on it.
2. **Values** (one word, from the same state the paint uses, `desired_colour`): `sent` (green: sent, replied, booked), `dropped` (red), `open` (no colour: still in play or waiting for the queue). Suppression-only rows (owner marks, no lead) take `sent` or `dropped` from the colour the owner applied. A row whose key cannot be located is left alone and counted.
3. **Sort-safe paint.** Match a tracked row to its live row by `row_key` over the whole tab, not by stored `sheet_row_no`; update `sheet_row_no` when it differs. A key that is missing or duplicated in the tab is skipped and counted (`moved`). Colour, `os_status` and the ownership rule (never over the owner's mark) are unchanged.
4. **Write path.** `sheet-paint` writes colours and `os_status` in the same run, preview by default and `--confirm` to write, still gated by `sheet_writeback_on`. Preview prints colour changes and `os_status` changes separately. `os_status` is written only where it differs, so a settled sheet costs no writes.
5. **Daily schedule.** `paint_tick` in `gtm/schedule.py`, same shape as `queue_tick`: one `sheet-paint --confirm` job per UTC day after `sheet_queue_hour_utc` plus one hour (so it runs after the queue), only when `sheet_writeback_on` and `sheet_id` are set. No new setting.

## 3. Out of scope
New rows for scraped leads, per-batch export tabs, the Settings buttons (Plan 8), conditional formatting (the owner's guidelines forbid it).

## 4. Tests
Unit: value mapping; header find or append; key relocation after a shuffled tab (rows sorted, one key deleted, one duplicated); idempotence. DB tests use `TEST_`/`REHEARSAL_` rows and a rehearsal sheet copy (`--sheet-id`), never the real sheet or real batches. `paint_tick` mirrors the `queue_tick` tests.

## 5. Gates
First write of `os_status` to the real sheet (preview, owner yes, then `--confirm`), then deploy (queue idle). Rehearse on a copy of the sheet first.
