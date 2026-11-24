# Plan 7: `os_status` column, daily paint, sort-safe rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** the OS writes an `os_status` column next to its colours, finds rows by key so sorting is safe, and paints daily.

**Architecture:** extend `gtm/sheet_paint.py` (locate by `row_key`, plan `os_status` cell writes beside colours), add one cell-writer to `gtm/sheet.py`, add `paint_tick` beside `queue_tick`. No migration: the live cell value is compared with the desired value, so nothing extra is stored.

**Tech Stack:** Python, Google Sheets API (`gtm/sheet.py`), pytest. Real Supabase for `db` tests only.

**Spec:** `docs/superpowers/specs/2026-11-24-plan7-os-status-design.md`

## Global Constraints
- Values are exactly `sent`, `dropped`, `open`. Header is exactly `os_status`.
- Never write inside a tab's painted width (header cells A..width), never over an owner mark (existing `plan_paint` rule unchanged), never touch the `Queue` tab.
- Preview is the default; writes only with `--confirm`; gated by `sheet_writeback_on` (existing).
- Tests: `TEST_`/`REHEARSAL_` rows, never real batches, real settings or the real sheet; one pytest process at a time (`until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done` ... `rmdir`).
- Every agent: `ponytail:ponytail`, `superpowers:test-driven-development`, graphify before grepping, `superpowers:verification-before-completion`.

## Review Focus
- Tab sorted by the owner between two paints: rows still found, colours and `os_status` land on the right rows (Task 2).
- Same `row_key` twice in a tab: skipped and counted, never painted (Task 2).
- Newyork's `os_status` lands past column Z: `read_tab` must read it (Task 1).
- Owner cleared an `os_status` cell or typed in it: OS rewrites only that cell, no other write (Task 3).
- Paint job fires twice in a UTC day or while write-back is off (Task 4).

---

### Task 1: `os_status` value, header lookup, cell writer
**Files:** Modify `gtm/sheet.py`, `gtm/sheet_paint.py`; Test `tests/test_sheet.py`, `tests/test_sheet_paint.py`
**Interfaces:**
- Produces: `os_status_value(status: str, owner_name: str | None, owner_email: str | None, queue_state: str | None) -> str` in `gtm/sheet_paint.py` (`sent` if `desired_colour` is green, `dropped` if red, else `open`); `os_col(header_cells: list[str]) -> tuple[int, bool]` in `gtm/sheet_paint.py` (0-based column of `os_status` and whether it already exists; if missing, the index right after the last non-empty header cell); `write_cells(svc, sheet_id: str, tab: str, cells: list[tuple[int, int, str]]) -> int` in `gtm/sheet.py` (row_no 1-based, col 0-based, text; one `batchUpdate`, `userEnteredValue` only).
- [ ] Failing tests: `test_os_status_value_table` (rows for sent, replied, rejected, no_buyer waiting, no_buyer failed, signalled; asserts the three values); `test_os_col_finds_existing_or_appends_after_last_header` (A..T header returns `(20, False)`; a header holding `os_status` at index 21 returns `(21, True)`); `test_write_cells_sends_one_batch_update_with_values_only` (fake svc records the body: one request per cell, `fields` is `userEnteredValue`).
- [ ] Run them, expect FAIL. Implement the three functions. Run, expect PASS.
- [ ] Widen `read_tab`'s range from `A:Z` to `A:AZ`; test `test_read_tab_reads_past_column_z` with a fake response asserting the requested range string.
- [ ] Commit `sheet: os_status value, header lookup, cell writer`.

### Task 2: locate tracked rows by `row_key` (sort-safe)
**Files:** Modify `gtm/sheet_paint.py` (`_tracked_and_live`); Test `tests/test_sheet_paint.py`
**Interfaces:** Consumes Task 1 nothing. Produces `_tracked_and_live` returning rows whose `sheet_row_no` is the LIVE row number (stored value updated in memory) plus the `moved` count, now meaning key missing or duplicated.
- [ ] Failing tests: `test_sorted_tab_rows_are_found_by_key` (tracked `sheet_row_no` 5 and 6 swapped in the live tab: both returned with live numbers 6 and 5); `test_missing_or_duplicate_key_is_skipped_and_counted` (one key deleted, one appearing twice: both skipped, `moved == 2`); update `test_tracked_and_live_joins_width_and_skips_moved_and_blank_rows` to the new meaning.
- [ ] Run, expect FAIL. Implement: build `{row_key: [(block, row_no, width)]}` from `map_tab`; a key with exactly one live match is located there, otherwise counted in `moved`. Run, expect PASS.
- [ ] In `run_paint`, when confirmed, persist the live `sheet_row_no` where it differs (one update per changed row). Test with the fake db in `test_run_paint_previews_then_paints_and_records`.
- [ ] Commit `sheet-paint: find rows by key, so sorting the tab is safe`.

### Task 3: write `os_status` in `run_paint`
**Files:** Modify `gtm/sheet_paint.py` (`run_paint`, new `plan_status`); Test `tests/test_sheet_paint.py`
**Interfaces:** Consumes Task 1 `os_status_value`, `os_col`, `write_cells`; Task 2 located rows. Produces `plan_status(tracked: list[dict], live_status: dict[tuple[str, int, str], str], cols: dict[str, int]) -> list[tuple[str, int, int, str]]` returning `(tab, row_no, col, value)` only where the live cell differs from the desired value.
- [ ] Tracked rows now also include suppression-only `sheet_rows` (lead_id null): select `suppression_id` too; their value comes from `colour_seen` (`green` is `sent`, `red` is `dropped`).
- [ ] Failing tests: `test_plan_status_only_where_different` (equal cell yields nothing; owner-cleared cell yields one write); `test_suppression_only_row_takes_value_from_its_colour`; `test_preview_prints_colour_and_status_changes_separately_and_writes_nothing` (assert no `write_cells` or `paint_rows` call without confirm); `test_confirm_writes_header_once_then_values` (missing header: header cell `os_status` written once with the values).
- [ ] Run, expect FAIL. Implement; the output lines are `Tab row N: os_status sent` and `N status cells`. Run, expect PASS.
- [ ] Commit `sheet-paint: write os_status beside the colours`.

### Task 4: daily paint tick (parallel with Tasks 1 to 3)
**Files:** Modify `gtm/schedule.py`, `gtm/worker.py:94` (call beside `queue_tick`); Test `tests/test_schedule.py`
**Interfaces:** Produces `paint_tick(db, now: datetime | None = None) -> str | None`.
- [ ] Failing tests mirroring `test_queue_tick_enqueues_once_per_day_and_respects_switch_and_hour`: `test_paint_tick_waits_one_hour_after_queue_hour`, `test_paint_tick_needs_writeback_on_and_sheet_id`, `test_paint_tick_once_per_utc_day_any_status`.
- [ ] Run, expect FAIL. Implement: same shape as `queue_tick`, job kind `sheet-paint`, argv `["--confirm"]`, condition `now.hour >= sheet_queue_hour_utc + 1` (cap at 23). Run, expect PASS.
- [ ] Commit `schedule: daily sheet-paint after the queue`.

### Task 5: rehearsal, docs, deploy gate
**Files:** Modify `docs/SHEET-GUIDELINES.md`, `docs/HANDOFF.md`, `CLAUDE.md` (one line)
- [ ] Full suite once under the lock; all pass.
- [ ] Rehearse `sheet-paint` preview on a copy of the sheet with `--sheet-id COPY` (dry run only); check counts against the real sheet's expectations.
- [ ] **Owner gate:** show the real-sheet preview, then wait for the owner's yes before `sheet-paint --confirm` on the real sheet; then deploy (queue idle).
- [ ] Guidelines: `os_status` is OS-owned, do not type in it; sorting is safe. HANDOFF section (h) and CLAUDE.md note the column and the daily paint.
- [ ] Whole-branch review on the most capable model, then merge.
