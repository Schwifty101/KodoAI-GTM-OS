# Plan 5: Sheet import, colour write-back and manual queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the owner's MedSpa Google Sheet into the OS (suppression from coloured rows, candidate leads from uncoloured rows), keep it in sync one way, paint row colours back, and run a daily ContactOut manual queue through a `Queue` tab.

**Architecture:** One Sheets client (`gtm/sheet.py`, OAuth as `soban@kodoai.xyz`, separate token) feeds pure planning functions (`gtm/sheet_map.py`, `gtm/sheet_import.py`, `gtm/sheet_queue.py`, `gtm/sheet_paint.py`) that are tested with a fake client; thin CLI passes run on the existing worker. One additive migration adds `sheet_rows` and `leads.owner_linkedin`. Candidates then use the existing `clean`, signals, select and draft passes.

**Tech Stack:** Python 3.14, supabase-py, google-api-python-client (already used by `gtm/gmail.py`), httpx (Hunter), pytest (`db` marker for real-Supabase tests), Next.js settings page mirror (`web/lib/settings.ts`).

**Spec:** `docs/superpowers/specs/2026-11-17-plan5-sheet-import-and-manual-queue-design.md` (read it and CLAUDE.md Rules and Sending first). Outline and execution rules: `docs/superpowers/plans/2026-11-17-plan5-outline.md` section 6.

## Global Constraints

- Read colours from `userEnteredFormat.backgroundColor` only. Pure green `(0,1,0)` = sent, pure red `(1,0,0)` = dropped; any other fill means nothing. A row with both counts as red.
- Green and red rows become `suppression` rows only (reasons `sheet-sent`, `sheet-dropped`), never leads. Entries hold the exact email(s) and the website domain; never a free-mail or platform domain (reuse `gtm.replies.FREE_MAIL` and `gtm.clean.PLATFORM_DOMAINS`, as `gtm/import_history.py` does).
- Uncoloured rows with an email become leads with status `scraped`, `email_source='sheet'`, `email_verified=false`; they go through the normal `clean`. `place_id` is the Maps place id parsed from `maps_url`, else `domain:<domain>`.
- Enriched needs Hunter `valid` and score >= 80, a decision-maker title and a non-role address (`gtm.buyer.pick_buyer`); `accept_all` and `webmail` fail. A sheet `email_verification` value never skips Hunter.
- Field map (only these are read): `name, category, website, owner_name, owner_title, owner_linkedin, owner_email, maps_url, city`, plus `state` from the tab name (Utah UT, Newyork NY, Texas TX).
- Sync is one way (sheet to OS). A lead at `drafted` or later is never changed by the sheet. New colours add suppression only; nothing is un-suppressed.
- The OS never overwrites an owner-applied colour. It writes only data-row colours and the `Queue` tab.
- Every import run and the first paint are dry runs; writes need `--confirm`. Every paid call goes through `budget.require` then a `cost_log` row. Import verification draws on its own lifetime allowance (`import_hunter_allowance_credits`), not the daily cap.
- Hard gates (stop and ask the owner): applying migration 0015; storing the Sheets token in Secret Manager; any write to the real sheet; any paid Hunter call; deploying to the VM (queue idle); merging to `main`. Never print keys or lead data into docs or commits.
- Tests: fake Sheets client built from the recon shapes; real-DB tests use `TEST_` place ids and clean up; manual rows use `REHEARSAL_`; tests never touch the real mailbox row or the real sheet; one pytest process at a time (`until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done`, `rmdir` after); run only your own test files until the merge.

## Review Focus

- A row with both a green and a red cell: dropped wins (Task 2, Task 5).
- A webmail address (`someone@gmail.com`) in a coloured row: suppression holds the email and the website domain, never `gmail.com` (Task 5).
- A cell holding two addresses, and a row with no email and no website: split, or skipped with a reason in the report (Task 4, Task 5).
- A sheet edit to a lead that is already `drafted`: skipped, reported, lead unchanged (Task 7).
- An email pasted into a Queue row whose lead is no longer `waiting`: ignored and listed (Task 9).
- A renamed tab, missing header row or an empty sheet: a clear error naming the tab, not a crash or a half write (Task 4).
- The OS's own red repainted as an owner mark on re-import (Task 5, Task 11).

## Execution waves (parallel worktrees, one agent per group, same preamble as the outline section 6)

| Wave | Group (own worktree and branch) | Tasks |
|---|---|---|
| 1 | A sheet client | 2, then 10 (same file) |
| 1 | B data and settings | 1 |
| 1 | C Hunter verifier and allowance | 3 |
| 2 | D import and sync | 4, 5, 7 (after 1 and 2) |
| 2 | E verify and queue | 6, 8, 9 (after 1, 2, 3) |
| 2 | F write-back | 11 (after 1, 2 and 10) |
| 3 | orchestrator-assigned single agent | 12 wiring and docs, then 13 acceptance |

Tasks 4, 5, 7 touch only `gtm/sheet_map.py`, `gtm/sheet_import.py`; 6 touches `gtm/sheet_verify.py`; 8, 9 `gtm/sheet_queue.py`; 10 `gtm/sheet.py` (write side, same group as Task 2, done in wave 1 because Tasks 9 and 11 use it); 11 `gtm/sheet_paint.py`. Only Task 12 edits `gtm/cli.py`, `gtm/worker.py`, `gtm/schedule.py`, so waves never conflict.

---

### Task 1: Migration 0015 and settings

**Files:**
- Create: `supabase/migrations/0015_sheet_rows.sql`
- Modify: `gtm/settings_store.py` (DEFAULTS), `web/lib/settings.ts`
- Test: `tests/test_settings_store.py` (add), `tests/test_sheet_rows_schema.py` (create, marker `db`)

**Interfaces:**
- Produces: table `sheet_rows(id uuid pk, tab text, block int, row_key text, lead_id uuid null references leads(id) on delete set null, suppression_id uuid null, sheet_row_no int, content_hash text, colour_seen text, colour_written text, written_at timestamptz, last_seen_at timestamptz, orphaned boolean default false, queue_state text null check in ('waiting','verified','failed'), created_at timestamptz default now(), unique (tab, block, row_key))` with RLS `operator_all`; column `leads.owner_linkedin text`; settings `sheet_id` (str, ""), `sheet_queue_size` (int, 5), `sheet_queue_on` (bool, False), `sheet_queue_hour_utc` (int, 13), `sheet_writeback_on` (bool, False), `import_hunter_allowance_credits` (float, 0.0).

- [ ] **Step 1: Write the failing tests.** `test_sheet_rows_schema.py::test_sheet_rows_unique_per_tab_block_key` inserts the same `(tab, block, row_key)` twice and expects the second insert to raise; `::test_owner_linkedin_column_exists` selects `owner_linkedin` from `leads`; `test_settings_store.py::test_sheet_defaults` asserts each default above through `setting(key)`.
- [ ] **Step 2: Run them; expect FAIL** (`uv run pytest tests/test_settings_store.py tests/test_sheet_rows_schema.py -q`).
- [ ] **Step 3: Write the migration and add the settings keys** (mirror each key in `web/lib/settings.ts` using that file's existing field shape and group "Sheet"). **Do not apply the migration: ask the owner (hard gate); the db tests run only after it is applied.**
- [ ] **Step 4: Run the settings test; expect PASS. After the owner applies 0015, run the schema tests; expect PASS.**
- [ ] **Step 5: Commit** `feat: sheet_rows table, owner_linkedin and sheet settings`.

### Task 2: Sheets client, read side

**Files:**
- Create: `gtm/sheet.py`
- Modify: `deploy/fetch_secrets.py` (optional secret `sheets-token` written to `token_sheets.json`, same handling as `gmail-token`)
- Test: `tests/test_sheet.py`, `tests/test_deploy_files.py` (add)

**Interfaces:**
- Produces:
  - `SHEET_SCOPE = "https://www.googleapis.com/auth/spreadsheets"`
  - `@dataclass class SheetRow: tab: str; row_no: int; cells: list[str]; colours: list[str | None]`
  - `colour_of(bg: dict | None) -> str | None` returns `"green"` or `"red"` when each channel is within 0.02 of pure green or pure red, else `None` (missing channels count as 0; white, tints and header blues are `None`).
  - `sheets_service()`: OAuth with `.secrets/token_sheets.json` and `google_oauth_client_file`, `login_hint="soban@kodoai.xyz"`; headless (no tty) with a missing or invalid token raises `RuntimeError` naming the file, like `gmail_service`.
  - `read_tab(svc, sheet_id: str, tab: str) -> list[SheetRow]`: one `spreadsheets.get` with `includeGridData`, fields `sheets.data.rowData.values(formattedValue,userEnteredFormat.backgroundColor)`, range `'<tab>'!A:Z`; keeps non-blank rows only, cells padded to the row's last value and returned as strings; a tab that does not exist raises `ValueError(f"tab {tab!r} not found in sheet")`.

- [ ] **Step 1: Write failing tests** with a hand-built fake `svc` returning the Sheets response shape: `test_colour_of_pure_green_red_only` (pure green and red map; `(0.72,0.88,0.8)`, `(0.97,0.84,0.85)`, `(1,0.95,0.8)`, `(0.24,0.52,0.78)`, white and `None` all give `None`); `test_read_tab_ignores_effective_format` (response carries only the requested `userEnteredFormat`); `test_read_tab_skips_blank_rows_and_numbers_rows_from_1`; `test_read_tab_missing_tab_raises_value_error`; `test_headless_without_token_raises` (monkeypatch `sys.stdin.isatty` to False, point `SECRETS` at a tmp dir); `test_fetch_secrets_writes_sheets_token` in the deploy test pattern already used for the Gmail token.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the interfaces above. The Mac consent flow is run once by the owner (`! uv run python -c "from gtm.sheet import sheets_service; sheets_service()"`); the Secret Manager copy for the VM is a separate owner-approved gate (Task 12).
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: Sheets client with exact-colour reading`.

### Task 3: Hunter email verifier and the import allowance

**Files:**
- Modify: `gtm/hunter.py`, `gtm/budget.py`
- Test: `tests/test_hunter.py`, `tests/test_budget.py` (add)

**Interfaces:**
- Produces:
  - `HunterPool.verify_email(self, email: str, bucket: str = "hunter") -> dict` returns `{"email": email, "verification_status": <data.status>, "score": <data.score>}` from `GET email-verifier?email=`, logs `log_cost(bucket, 0.5, None, batch_id, note=f"verify:{domain}")`.
  - `HunterPool._call(path, params, bucket="hunter", amount=1.0)` passes both to `budget.require`.
  - `budget.CAP_KEYS["hunter_import"] = "import_hunter_allowance_credits"`; `require("hunter_import", n)` compares the **lifetime** sum of `cost_log` units for provider `hunter_import` plus `n` with the setting. Daily `hunter` spend never includes it.

- [ ] **Step 1: Write failing tests** with the fake `http`: `test_verify_email_returns_status_and_score_and_logs_half_credit` (fake body `{"data":{"status":"valid","score":96}}`; one log row with units 0.5); `test_verify_email_import_bucket_logs_hunter_import_provider`; `test_import_bucket_is_lifetime_and_separate` (allowance 1.0, two 0.5 spends pass, the third raises `BudgetExceeded` even on a new day; daily `hunter` spend unchanged); `test_import_spend_not_counted_in_daily_cap`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `require` gets one branch for `hunter_import` (sum all rows, no midnight bound); everything else unchanged.
- [ ] **Step 4: Run `tests/test_hunter.py tests/test_budget.py`; expect PASS.**
- [ ] **Step 5: Commit** `feat: Hunter verifier with a separate import allowance`.

### Task 4: Tab mapping and block detection

**Files:**
- Create: `gtm/sheet_map.py`
- Test: `tests/test_sheet_map.py`

**Interfaces:**
- Consumes: `SheetRow` (Task 2).
- Produces:
  - `TAB_STATE = {"Utah": "UT", "Newyork": "NY", "Texas": "TX"}`
  - `blocks(rows: list[SheetRow]) -> list[tuple[dict[str, int], list[SheetRow]]]`: a header row is one whose first cell lower-cased is `business` or `Company`; each header starts a block; rows before the first header or an empty result raise `ValueError` naming the tab.
  - `header_map(cells: list[str]) -> dict[str, int]` maps field -> column index by header text, case-insensitive: `business|company -> name`; `maps_category -> category`; `website`; `buyer_name|buyer -> owner_name`; `buyer_role|role -> owner_title`; `linkedin_url|linkedin (confirmed) -> owner_linkedin` (`linkedin (to check)` is the fallback used only when the confirmed cell is empty); `email -> owner_email`; `maps_url`; `city|metro -> city`. Real headers: Utah block 1 and Newyork `business, maps_category, website, buyer_name, buyer_role, linkedin_url, email, email_person, other_people, maps_url`; Texas adds `metro`, `email_verification`, `buyer_verdict`; Utah block 2 (row 20) `Company, City, Website, Fit, Buyer, Role, Role check, Role evidence (quote), Role evidence URL, LinkedIn (confirmed), LinkedIn (to check), Email, Email type, Email status, Email source, Notes`. Unknown headers are ignored.
  - `@dataclass class MappedRow: tab: str; block: int; row_no: int; fields: dict[str, str]; emails: list[str]; colour: str | None; width: int` where `colour` is `red` if any cell is red, else `green` if any is green, else `None`; `emails` is `owner_email` split on whitespace, commas and semicolons, lower-cased, only tokens containing `@`; `width` is the header's last non-empty column count (used by painting); `fields` includes `state` from `TAB_STATE`.
  - `map_tab(tab: str, rows: list[SheetRow]) -> list[MappedRow]` (data rows only, header rows excluded, blocks numbered from 1).

- [ ] **Step 1: Write failing tests** from fixtures that copy the recon shapes (invented business names): `test_utah_two_blocks_have_separate_headers` (block 1 header row 1, block 2 header row 20 with no blank row between); `test_utah_block2_columns_map_by_header_text`; `test_texas_metro_maps_to_city_and_extra_columns_ignored`; `test_two_emails_in_one_cell_are_split_and_lowercased`; `test_red_wins_over_green`; `test_colour_in_any_cell_marks_the_row`; `test_state_comes_from_tab_name`; `test_missing_header_raises_value_error_naming_tab`; `test_linkedin_falls_back_to_to_check_column`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: tab mapping with Utah two-block detection`.

### Task 5: Import plan and `import-sheet` pass

**Files:**
- Create: `gtm/sheet_import.py`
- Test: `tests/test_sheet_import.py` (pure), `tests/test_sheet_import_db.py` (marker `db`)

**Interfaces:**
- Consumes: `MappedRow` (Task 4), `_domain` from `gtm.scrape`; `FREE_MAIL`, `PLATFORM_DOMAINS`.
- Produces:
  - `place_key(row: MappedRow) -> str`: place id parsed from `fields["maps_url"]` (the `ChIJ…` token or `place_id:` form) else `domain:<domain of website>`; a row with neither raises `ValueError` and is reported as skipped.
  - `plan_import(rows: list[MappedRow], have_emails: set[str], have_domains: set[str], have_place_ids: set[str], tracked: dict[tuple[str,int,str], dict]) -> ImportPlan` with `ImportPlan(suppress: list[dict], leads: list[dict], skipped: list[tuple[str, str]], left_for_queue: int, tracked_new: list[dict])`. Suppress dicts are `{"email"|"domain", "reason"}` (same shape as `history_rows`); a webmail or platform domain never becomes a `domain` row. A coloured row with no email and no website domain is `skipped` with reason `nothing_to_match`. Uncoloured rows with at least one email become lead dicts (`place_id`, `name`, `website`, `domain`, `category`, `city`, `state`, `owner_name`, `owner_title`, `owner_linkedin`, `owner_email` = first email, `email_source="sheet"`, `email_verified=False`, `status="scraped"`); registered-agent buyers (title or name containing `registered agent` or `service of process`) are stored with `owner_name=None`; rows already tracked or already known by place id, email or domain are `skipped`; uncoloured rows with no email and a named buyer increment `left_for_queue`.
  - `run_import_sheet(db, svc, sheet_id: str, confirm: bool = False) -> ImportPlan`: reads every tab in `TAB_STATE`, builds the plan against current DB state, prints a per-tab report (green, red, uncoloured, suppress rows, leads, skipped by reason, left for queue), and writes only when `confirm`: inserts suppression rows, creates one batch named `Sheet import <date>`, inserts leads in it, and inserts `sheet_rows` rows (`colour_seen`, `content_hash`, `lead_id` or `suppression_id`, `colour_written=None`). Idempotent: running it twice adds nothing.

- [ ] **Step 1: Write failing tests:** `test_green_and_red_rows_become_suppression_with_their_reasons`; `test_webmail_email_row_suppresses_email_and_website_domain_not_gmail_com`; `test_row_with_no_email_and_no_website_is_skipped_nothing_to_match`; `test_uncoloured_row_with_email_becomes_scraped_lead_with_sheet_source`; `test_place_id_from_maps_url_else_domain_key`; `test_registered_agent_buyer_is_dropped_from_the_lead`; `test_known_email_or_domain_is_skipped`; `test_uncoloured_named_row_without_email_counts_left_for_queue`; `test_tab_not_found_error_writes_nothing` (db); `test_dry_run_writes_nothing_and_confirm_is_idempotent` (db, `TEST_` keys, cleanup of suppression and leads and sheet_rows).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `plan_import` as a pure function and `run_import_sheet` as the only writer. Suppression `domain` values come from `gtm.scrape._domain(website)`.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: sheet import plan and dry-run-first import pass`.

### Task 6: Verify the imported candidates (`verify-sheet`)

**Files:**
- Create: `gtm/sheet_verify.py`
- Test: `tests/test_sheet_verify.py`

**Interfaces:**
- Consumes: `HunterPool.verify_email(email, bucket)` (Task 3), `gtm.buyer.pick_buyer`.
- Produces: `run_verify_sheet(db, pool, batch_id: str, limit: int | None = None, bucket: str = "hunter_import") -> dict[str, int]`: for each lead in the batch with `status='cleaned'`, `email_source='sheet'`, `owner_email` set and `email_verified` false, verifies the address, then builds the candidate `{email, first_name, last_name, position: owner_title, verification_status, score}` and applies `pick_buyer`. A pass sets `status='enriched'`, `email_verified=True`; a fail sets `no_buyer`, keeping `owner_name` and `owner_title` and clearing nothing else. Returns counts `enriched`, `no_buyer`, `out_of_credits` (an `OutOfCredits` or `BudgetExceeded` leaves the lead `cleaned` and stops). The function never runs without a caller passing a real pool; the CLI pass (Task 12) refuses without `--confirm` and prints the credit estimate (0.5 per lead) first.

- [ ] **Step 1: Write failing tests** with a fake pool: `test_valid_score_80_decision_maker_becomes_enriched`; `test_accept_all_and_webmail_fail_to_no_buyer`; `test_role_address_info_at_fails`; `test_failed_lead_keeps_owner_name_and_title`; `test_budget_exceeded_stops_and_leaves_lead_cleaned`; `test_lead_without_a_decision_maker_title_is_no_buyer`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Reuse `pick_buyer`; split `owner_name` into first and last as `gtm.enrich` does for saved names.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: verify sheet candidates against Hunter within the import allowance`.

### Task 7: Sync from the sheet

**Files:**
- Modify: `gtm/sheet_import.py`
- Test: `tests/test_sheet_import.py` (add)

**Interfaces:**
- Produces: `plan_sync(rows: list[MappedRow], tracked: dict, leads_by_id: dict[str, dict]) -> SyncPlan` with `SyncPlan(updates: list[tuple[str, dict]], reverify: list[str], frozen: list[tuple[str, dict]], orphaned: list[str], new_suppress: list[dict])`, used inside `run_import_sheet` after the add pass.
  - A tracked row whose `content_hash` changed updates `name, website, domain, owner_name, owner_title, owner_linkedin, owner_email` on its lead. A changed email also sets `status='cleaned'`, `email_verified=False` and lists the lead in `reverify` (Task 6 picks it up).
  - A lead whose status is `drafted`, `sent`, `replied`, `booked`, `bounced`, `suppressed` or `unsubscribed` is never updated: the diff goes to `frozen` and the report.
  - A tracked key no longer present in the sheet is `orphaned` (flag only). A row that is now green or red and was not before (and whose colour is not the OS's own `colour_written`) adds suppression like Task 5.

- [ ] **Step 1: Write failing tests:** `test_changed_email_updates_lead_and_queues_reverify`; `test_drafted_lead_is_frozen_and_reported_not_changed`; `test_deleted_or_rekeyed_row_is_orphaned_not_deleted`; `test_new_red_colour_adds_suppression`; `test_os_written_red_is_not_read_as_owner_mark`; `test_unchanged_hash_makes_no_updates`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `plan_sync` as a pure function and call it from `run_import_sheet` (writes only with `confirm`).
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: one-way sheet sync with drafted leads frozen`.

### Task 8: Queue selection

**Files:**
- Create: `gtm/sheet_queue.py`
- Test: `tests/test_sheet_queue.py` (pure), `tests/test_sheet_queue_db.py` (marker `db`)

**Interfaces:**
- Produces:
  - `queue_order(leads: list[dict]) -> list[dict]`: named owner first, then `owner_linkedin` present, then `review_count` desc then `rating` desc (nulls last, so sheet-only rows sort after DB leads that have them).
  - `select_queue(db, n: int) -> list[dict]`: leads with `status='no_buyer'`, `owner_name` set, `owner_email` null, whose `sheet_rows` queue entry is not `failed`, `verified` or `waiting`, ordered by `queue_order`, first `n`; reads at most `n` after the order; excludes suppressed leads through `gtm.select.blocked_reason` with the current suppression and contacted sets.
  - `pull_sheet_only(db, svc, sheet_id) -> int`: uncoloured named rows without an email from the data tabs that have no lead yet are inserted `scraped` in the `Sheet import` batch, run through `gtm.clean.run_clean`, and those that pass are set `no_buyer` with their saved name and a `sheet_rows` entry; returns how many became `no_buyer`. Never runs the paid enrich finders.

- [ ] **Step 1: Write failing tests:** `test_order_named_then_linkedin_then_reviews_then_rating`; `test_sheet_only_rows_sort_after_rows_with_reviews`; `test_failed_lead_is_never_requeued`; `test_waiting_lead_is_not_selected_twice`; `test_suppressed_lead_is_not_selected`; `test_pull_sheet_only_inserts_scraped_then_cleans_then_no_buyer` (db).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: manual queue selection and sheet-only pull-in`.

### Task 9: Queue tab run (write, read back, verify)

**Files:**
- Modify: `gtm/sheet_queue.py`
- Test: `tests/test_sheet_queue.py` (add)

**Interfaces:**
- Consumes: `read_tab`, `write_queue_tab` (Task 10), `select_queue`, `pull_sheet_only` (Task 8), `HunterPool.verify_email` (Task 3), `pick_buyer`.
- Produces: `run_queue(db, svc, pool, sheet_id: str, size: int, confirm: bool = False) -> dict[str, int]`. Queue tab columns: `business, owner_name, domain, linkedin_search, email, status, lead_id`. Order of work: (1) read the `Queue` tab; (2) for each row whose `lead_id` is `waiting` and whose `email` is filled, verify via the daily `hunter` bucket (queue spend is not import spend) and apply `pick_buyer`: pass sets `enriched`, `email_verified=True`, `owner_email`, `email_source='contactout'` and `queue_state='verified'`; fail leaves `no_buyer` and sets `queue_state='failed'` (the pasted address is not stored); (3) rows pasted for a lead that is not `waiting` are counted `ignored` and listed; (4) top up `waiting` rows to `size` with `select_queue`, `linkedin_search` being `https://www.linkedin.com/search/results/people/?keywords=<owner_name>+<business>` URL-encoded; (5) rewrite the tab with waiting rows (keeping unpasted rows and emails already typed) plus new rows; finished rows disappear, each row's `status` reads `waiting`. Matching is by `lead_id` in the row, so sorting or filtering the tab is safe. Without `confirm`, it prints the plan (counts, credits) and writes and spends nothing.

- [ ] **Step 1: Write failing tests** (fake svc, fake pool): `test_valid_pasted_email_enriches_the_lead_and_removes_the_row`; `test_failed_pasted_email_leaves_no_buyer_and_marks_failed`; `test_paste_for_a_non_waiting_lead_is_ignored_and_listed`; `test_tab_is_topped_up_to_size_without_duplicates`; `test_sorted_tab_still_matches_by_lead_id`; `test_dry_run_writes_and_spends_nothing`; `test_budget_exceeded_keeps_row_waiting`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: manual queue run reads ContactOut pastes and tops up the tab`.

### Task 10: Sheets client, write side

**Files:**
- Modify: `gtm/sheet.py`
- Test: `tests/test_sheet.py` (add)

**Interfaces:**
- Produces:
  - `paint_rows(svc, sheet_id: str, tab: str, cells: list[tuple[int, int, str | None]]) -> int`: each tuple is `(row_no, width, colour)`; `colour` `"green"`, `"red"` or `None` (clear to white); builds one `spreadsheets.batchUpdate` of `repeatCell` requests (columns A to `width`, field `userEnteredFormat.backgroundColor`), resolving the numeric `sheetId` from the tab title; returns how many rows it painted.
  - `write_queue_tab(svc, sheet_id: str, rows: list[list[str]]) -> None`: creates the `Queue` tab if missing, clears `A:G`, writes the header and `rows` with `valueInputOption=RAW`.

- [ ] **Step 1: Write failing tests** (fake svc recording requests): `test_paint_rows_builds_one_batch_with_pure_colours`; `test_paint_clear_uses_white`; `test_write_queue_tab_creates_tab_when_missing`; `test_write_queue_tab_clears_then_writes_header_and_rows`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** No test calls the real sheet.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: Sheets client write side for painting and the Queue tab`.

### Task 11: Colour write-back

**Files:**
- Create: `gtm/sheet_paint.py`
- Test: `tests/test_sheet_paint.py`

**Interfaces:**
- Consumes: `paint_rows` (Task 10), `read_tab`, `MappedRow` colours, `sheet_rows`.
- Produces:
  - `desired_colour(status: str, owner_name: str | None, owner_email: str | None, queue_state: str | None) -> str | None`: `green` for `sent`, `replied`, `booked`; `red` for `rejected`, `suppressed`, `bounced`, `unsubscribed`, and for `no_buyer` **unless** the lead has an `owner_name`, no `owner_email` and `queue_state != 'failed'` (a named lead still waiting for the queue stays uncoloured); `None` for everything else (`scraped`, `cleaned`, `enriched`, `signalled`, `selected`, `drafted`).
  - `is_ours(row_colours: list[str | None], width: int, written: str | None) -> bool`: true only when `written` is set and every cell in columns 1 to `width` shows exactly that colour.
  - `plan_paint(tracked_rows: list[dict], live: dict[tuple[str,int,str], list[str | None]]) -> list[tuple[str, int, int, str | None]]`: per tracked data row, skip when the row shows an owner colour (not ours and not blank), skip when already as desired, otherwise paint (or clear an OS red or green whose lead state moved back to `None`).
  - `run_paint(db, svc, sheet_id: str, confirm: bool = False) -> int`: needs setting `sheet_writeback_on` (else raises `RuntimeError` saying the switch is off); prints the preview (rows, colours) and paints only with `confirm`; afterwards records `colour_written` and `written_at`.

- [ ] **Step 1: Write failing tests:** `test_desired_colour_table` (parametrised, including a named no-email `no_buyer` -> `None` and the same lead with `queue_state='failed'` -> `red`); `test_owner_painted_row_is_never_overwritten`; `test_os_paint_is_recognised_only_when_every_cell_matches`; `test_owner_cleared_os_paint_is_left_alone_until_state_changes`; `test_retried_no_buyer_that_becomes_enriched_loses_its_os_red`; `test_paint_width_follows_the_block_header_not_a_fixed_ten_columns`; `test_writeback_switch_off_refuses`; `test_queue_tab_and_untracked_leads_are_never_painted`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Painting width is `MappedRow.width` (so Utah block 2 is painted across its 16 header columns), which refines the design's "columns A to J" for that block.
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `feat: colour write-back that never overwrites the owner's marks`.

### Task 12: CLI, worker, schedule and docs

**Files:**
- Modify: `gtm/cli.py`, `gtm/worker.py` (ALLOWED), `gtm/schedule.py`, `docs/HANDOFF.md`, `CLAUDE.md` (Commands), `docs/runbooks/cloud-runner.md`
- Test: `tests/test_cli.py`, `tests/test_worker.py`, `tests/test_schedule.py` (add)

**Interfaces:**
- Produces CLI commands: `import-sheet [--confirm] [--tab T]`, `verify-sheet --batch ID [--confirm] [--limit N]` (prints `0.5 x N` credits first, refuses without `--confirm`), `sheet-queue [--confirm]`, `sheet-paint [--confirm]`. All read `sheet_id` from Settings and refuse with a clear message when empty. Worker `ALLOWED` gains `import-sheet`, `verify-sheet`, `sheet-queue`, `sheet-paint`. `schedule.queue_tick(db, now=None) -> str | None` enqueues one `sheet-queue` job (argv `--confirm`) per UTC day when `sheet_queue_on` and the hour has passed, mirroring `tick`.

- [ ] **Step 1: Write failing tests:** parser accepts each command and `--confirm` defaults false; `test_sheet_commands_refuse_when_sheet_id_empty`; `test_verify_sheet_refuses_without_confirm`; `test_worker_allows_the_new_kinds`; `test_queue_tick_enqueues_once_per_day_and_respects_switch_and_hour`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Wire the commands and `queue_tick`** (call it from the worker loop beside `tick`). Update HANDOFF section 0 (Plan 5 row), CLAUDE.md Commands and the runbook (consent steps, the Secret Manager `sheets-token`, the gates).
- [ ] **Step 4: Run the new tests, then the full suite once (one pytest process); expect all PASS.**
- [ ] **Step 5: Commit** `feat: sheet commands, worker kinds and the morning queue schedule`.

### Task 13: Acceptance (the owner is present; every real write or spend needs a yes)

- [ ] **Step 1:** After the owner applies migration 0015 and runs the Sheets consent on the Mac, run `uv run python -m gtm.cli import-sheet` (dry run, read-only against the real sheet). Expect a per-tab report near the recon: green 65, red 19, uncoloured with email 87 (Utah 1, Newyork 33, Texas 53) before skips.
- [ ] **Step 2:** Owner reads the report. On a yes: `import-sheet --confirm`, then `clean --batch <id>`, then `verify-sheet --batch <id>` prints the credit estimate; the owner sets `import_hunter_allowance_credits` and says go before `--confirm`.
- [ ] **Step 3:** `sheet-paint` dry run shows the preview; the owner approves the first write; `sheet-queue` dry run, then one real run with 5 rows.
- [ ] **Step 4:** Whole-branch review, full suite, PR. Deploy to the VM only when the queue is idle and the owner says so; the owner then stores the Sheets token in Secret Manager.
