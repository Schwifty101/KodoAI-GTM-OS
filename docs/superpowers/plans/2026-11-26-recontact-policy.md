# Plan 9: recontact policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A contact the OS or the owner mailed can be approached again about 90 days after its last send when it never replied, with no block weakened; the pre-OS history qualifies from a backfill.

**Architecture:** A pure policy module `gtm/recontact.py` (what is released), one flag-gated change inside `_blocklists` in `gtm/select.py` (the single choke point every caller uses), a new table `contact_history` (migration 0018, owner applies), a backfill module, and a `recontact` pass that creates a new lead per round after Hunter re-verification. `suppression` and `touches` do not change.

**Tech Stack:** Python, pytest, supabase-py, Next.js, TypeScript, tsx scripts.

**Spec:** `docs/superpowers/specs/2026-11-26-recontact-policy-design.md`

## Global Constraints
- Docs-style rules: no emojis, no invented numbers. 90 days is the owner's; 3 rounds is my recommendation (setting, not a measurement); 7 days is derived from the Day 0/3/7 cadence.
- Fail closed everywhere: no ledger row, flag off, a setting below 1, a ledger read error, an unknown suppression reason or an `unknown` outcome all mean "still blocked". `blocked_reason` keeps its signature; `suppression` rows are never edited or deleted by code in this plan; the flag-off path never reads `contact_history` (so code can deploy before the migration).
- Cooldown suppression reasons are exactly `notion-contacted` and `sheet-sent`; every other reason is permanent. Clear outcomes are exactly `no_reply` and `auto_reply`.
- A recontact lead is created in its final status (`enriched` or `no_buyer`), never `cleaned`: autopilot would run enrich on a `cleaned` lead. Autopilot gets no recontact stage. Never auto-send, never auto-start.
- Every paid call writes `cost_log` (bucket `hunter_recontact`, lifetime allowance from `recontact_hunter_allowance_credits`, default 0). Never print keys, addresses or names in reports: counts only.
- Tests: `TEST_` place ids and `TEST` batch names; ledger test rows carry `source_ref = 'TEST'`; cleanup deletes only the ids a test created. Never `like('place_id','recontact:%')` or any wildcard over real prefixes (a TEST_ wildcard once wiped rehearsal leads and a reason-keyed cleanup once wiped real suppression rows). Run one pytest or verify process at a time (`until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done` ... `rmdir /tmp/gtm-pytest.lock`). Autopilot is live on the real database: run `web` verify scripts only with it paused.
- Do not commit unless the executor is told to; do not touch the untracked Codex files. Every agent: `ponytail:ponytail`, `superpowers:test-driven-development`, graphify before grepping, `superpowers:verification-before-completion`.

## Review Focus
- Absent, empty or unreadable ledger never lifts a block; with the flag off `_blocklists` equals today's function and makes no ledger query (Tasks 2, 3).
- A lead with any reply, bounce, unsubscribe, suppression or booking stays `contacted` forever, even after 90 days: `replies.apply_reply` writes no suppression row for positive or neutral replies, so only the lead status protects them (Tasks 2, 3).
- A bounced contact's domain row has reason `notion-contacted`: the permanent email row must still block the domain (Task 2).
- `recontact_days` or `recontact_max_rounds` stored as 0 or negative must fall back, not lift everything (Task 1).
- `TEST_` and `REHEARSAL_` leads (3 `sent` touches from 2026-11-10 exist) are never candidates; an OS lead with an unsent touch is never a candidate (Task 6).
- Dry run writes and spends nothing; Apply needs the flag, `--limit` and allowance; a second run creates no duplicate (Task 6).
- A live twin lead (same domain or email, cleaned or later) is skipped (Task 6).
- Dates are never earlier than provable; a sheet-sent row stays blocked (outcome `unknown`) (Task 5).
- Existing select, draft, redraft, send, sheet_verify, sheet_queue and autopilot tests pass unmodified.

## Task groups (parallelisable)
Group A (sequential, no migration, no real writes): Tasks 1, 2, 3. Then Group B in parallel (disjoint new files): Tasks 4, 5, 6, 7. Then Group C: Tasks 8, 9 in parallel. Then Group D: Task 10.

### Task 1: Settings keys and the Hunter bucket (Group A)
**Files:** Modify `gtm/settings_store.py`, `gtm/budget.py`, `web/lib/settings.ts`; Test `tests/test_settings_store.py`, `tests/test_budget.py`, `web/scripts/settings_groups.mts`.
**Interfaces:** Produces `DEFAULTS` keys `recontact_on: False`, `recontact_days: 90`, `recontact_max_rounds: 3`, `recontact_hunter_allowance_credits: 0.0` (group "Recontact" in `SETTING_FIELDS`); `_ok` rejects `recontact_days` and `recontact_max_rounds` below 1 (the setting then falls back to the default); `budget.CAP_KEYS["hunter_recontact"] = "recontact_hunter_allowance_credits"`; `require` treats `hunter_recontact` like `hunter_import` (lifetime, epoch start, `kind` "credit").
- [ ] **Step 1:** Failing tests: `test_recontact_defaults_and_types`; `test_recontact_days_or_rounds_below_one_fall_back_to_default` (stored 0 and -5); `test_hunter_recontact_is_a_lifetime_allowance_that_defaults_to_zero` (default allowance: `require("hunter_recontact", 0.5)` raises `BudgetExceeded` with `kind == "credit"`; with allowance 1 and one old cost row of 0.5 it passes, then raises at the next 0.5).
- [ ] **Step 2:** Run `uv run pytest -q tests/test_settings_store.py tests/test_budget.py` (under the lock). Expected: FAIL.
- [ ] **Step 3:** Implement; mirror the four fields in `web/lib/settings.ts`. Run the two test files, `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/settings_groups.mts`, `npx tsc --noEmit`. Expected: pass.
- [ ] **Step 4:** Commit `settings: recontact keys and hunter_recontact bucket`.

### Task 2: Pure policy core `gtm/recontact.py` (Group A)
**Files:** Create `gtm/recontact.py`, `tests/test_recontact.py`.
**Interfaces:** Produces
- `COOLDOWN_REASONS = frozenset({"notion-contacted","sheet-sent"})`, `CLEAR_OUTCOMES = frozenset({"no_reply","auto_reply"})`, `OUTCOMES` (the 11 values of the migration check).
- `keys(email: str | None, domain: str | None) -> set[str]` (lowercase, empties dropped).
- `released_keys(sup: list[dict], hist: list[dict], today: date, days: int, max_rounds: int) -> set[str]`: `sup` rows `{email, domain, reason}`, `hist` rows `{email, domain, outcome, last_sent_on, round}`. A ledger row is clear when its outcome is in `CLEAR_OUTCOMES`, `last_sent_on + days <= today`, `round < max_rounds`, and none of its keys appears in a suppression row whose reason is not in `COOLDOWN_REASONS`. Result = keys of clear rows minus keys of every non-clear row minus every permanent key.
- `lead_released(lead: dict, touches: list[dict], today: date, days: int, max_rounds: int) -> bool`: true only when `lead.status == "sent"`, the place id is not `TEST_`/`REHEARSAL_`, no touch is in `drafted, held, edited, approved, scheduled, sending`, the newest sent touch is `days` old or more, and `lead.round < max_rounds`.
- `notion_outcome(status: str, reply: str, dnc: bool) -> str` (strictest wins: DNC, Bounce, Negative or Not Interested, Disqualified, Call Booked, Client, any other reply or status Replied, Out of Office is `auto_reply`, Sent or Follow-up Due or Cadence Complete is `no_reply`, else `unknown`).
- `last_sent_bound(initial: date, last: date | None) -> date` = `max(last, initial + 7 days)`.
- [ ] **Step 1:** Failing tests in `tests/test_recontact.py` (pure, no database): `test_keys_lowercase_and_drop_empty`; `test_released_keys_lifts_a_clear_old_cooldown_contact`; `test_released_keys_needs_a_ledger_row`; `test_released_keys_never_lifts_a_permanent_reason` (parametrized: do-not-contact, notion-bounce, bounce, not-interested, opt-out reply, sheet-dropped, an unknown reason); `test_a_permanent_row_on_any_shared_key_blocks_the_whole_contact` (bounced email row plus a `notion-contacted` domain row plus a clear ledger row: neither key is released); `test_released_keys_boundary_day_90_in_day_89_out`; `test_released_keys_unclear_outcome_recent_date_or_round_at_cap_blocks` (parametrized, including `unknown`); `test_one_unclear_ledger_row_taints_a_shared_domain`; `test_released_keys_is_always_a_subset_of_cooldown_keys_and_misses_permanent_keys` (seeded random data, 200 cases); `test_lead_released_only_when_sent_old_enough_and_closed` (parametrized: replied, booked, bounced, unsubscribed, suppressed, drafted touch open, 89 days, round at cap, TEST_ and REHEARSAL_ place ids all False; Touch 3 sent 90 days ago True); `test_notion_outcome_precedence` (parametrized over the table in the spec); `test_last_sent_bound_is_the_later_of_last_contacted_and_day_seven`.
- [ ] **Step 2:** Run `uv run pytest -q tests/test_recontact.py`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement pure functions, no imports from `gtm.db`. Rerun. Expected: pass.
- [ ] **Step 4:** Commit `feat: recontact policy core`.

### Task 3: `_blocklists` behind the flag (Group A)
**Files:** Modify `gtm/select.py`; Test `tests/test_select.py`.
**Interfaces:** Consumes Task 1 settings and Task 2 functions. Produces `_blocklists(db, today: date | None = None) -> tuple[set[str], set[str]]`, same return type. Flag off: today's code, byte for byte, no query to `contact_history`. Flag on: reads the ledger with `fetch_all`, `suppressed` = all suppression keys minus `released_keys`; `contacted` = keys of leads with a sent touch minus leads where `lead_released` is true (one paged read of touches in sent and open statuses, leads read in chunks of 100 as today). A ledger error propagates.
- [ ] **Step 1:** Failing tests with a small fake db (supabase-style table stub, no network): `test_blocklists_with_recontact_off_equals_the_old_function_and_never_reads_the_ledger` (the old function is copied into the test as `legacy`; the stub raises if `contact_history` is queried); `test_blocklists_on_lifts_a_suppression_key_only_with_a_clear_ledger_row`; `test_blocklists_on_keeps_a_replied_lead_contacted_forever`; `test_blocklists_on_lifts_an_old_sent_lead_with_no_reply`; `test_blocklists_on_ledger_read_error_raises`; `test_blocklists_on_keeps_every_permanent_reason`.
- [ ] **Step 2:** Run `uv run pytest -q tests/test_select.py -k blocklists`. Expected: FAIL.
- [ ] **Step 3:** Implement. Then run `tests/test_select.py tests/test_draft.py tests/test_redraft.py tests/test_send.py tests/test_sheet_verify.py tests/test_sheet_queue.py` unmodified. Expected: pass.
- [ ] **Step 4:** Commit `select: recontact release behind recontact_on`.

### Task 4: Migration file and schema test (Group B)
**Files:** Create `supabase/migrations/0018_contact_history.sql`, `tests/test_contact_history_schema.py`.
**Interfaces:** Produces the SQL in the spec (table, unique index, `leads.round`, `leads.history_id`, partial unique index, RLS `operator_only` copied from 0015). The file is written, never applied by the agent.
- [ ] **Step 1:** Tests (`db`; skip with "migration 0018 not applied" when the table is missing): `test_contact_history_unique_per_source_key_and_round`; `test_contact_history_needs_an_email_or_a_domain`; `test_contact_history_rejects_an_unknown_outcome_or_date_basis`; `test_leads_round_defaults_to_one`; `test_leads_history_id_is_unique_when_set`. Cleanup by `source_ref = 'TEST'` and returned ids only.
- [ ] **Step 2:** Write the migration; `uv run pytest -q tests/test_contact_history_schema.py`. Expected now: skipped. After the owner applies it (gate 1): all pass.
- [ ] **Step 3:** Commit `db: migration 0018 contact_history (not applied)`.

### Task 5: Backfill parsing and `backfill-contacts` (Group B)
**Files:** Create `gtm/contact_backfill.py`, `tests/test_contact_backfill.py`.
**Interfaces:** Consumes `notion_outcome`, `last_sent_bound`, `sheet_import._usable_domain`, `sheet_map.map_tab`. Produces
- `parse_notion_csv(text: str) -> list[dict]` (header-named columns as in the Notion CSV export: Founder, Role, Company, Email, Website, State, HQ City, Status, Reply Type, Touch, Initial Sent, Last Contacted, Do Not Contact, Subject, Vector Used, Campaign Batch; Email Body is read and dropped).
- `notion_ledger_rows(records: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]` (rows, skipped with reasons). One ledger row per contact: both keys, `source 'notion'`, `source_ref` the Campaign Batch, `date_basis 'exact'` only when Last Contacted is already the later date else `'upper_bound'`. A key seen in two batches merges to the latest date and the strictest outcome.
- `sheet_ledger_rows(rows: list[MappedRow], sheet_sent: dict[tuple, date], known: set[str]) -> list[dict]` (green rows only by import-time `sheet_rows.colour_seen`; `source 'sheet'`, outcome `unknown`, `upper_bound`, date from the matching `sheet-sent` suppression row; a row whose key is already in the Notion ledger is skipped).
- `run_backfill(db, rows: list[dict], confirm: bool) -> dict[str, int]` (writes only `contact_history`, in chunks of 200, only with `confirm`; never touches `suppression`; counts per outcome and per first-eligible week, no addresses).
- [ ] **Step 1:** Failing tests: `test_notion_row_becomes_one_ledger_row_with_both_keys`; `test_webmail_and_booking_domains_are_never_a_ledger_domain`; `test_row_without_a_send_date_gets_no_ledger_row_and_is_reported`; `test_datetime_initial_sent_is_cut_to_a_date`; `test_cadence_complete_with_no_reply_is_no_reply`; `test_out_of_office_is_auto_reply_and_dnc_beats_everything`; `test_same_contact_in_two_batches_merges_to_latest_date_and_strictest_outcome`; `test_sheet_green_row_is_unknown_with_an_upper_bound_date_from_its_suppression_row`; `test_sheet_row_already_in_the_notion_ledger_is_skipped`; `test_run_backfill_dry_run_writes_nothing` (stub fails on any insert); `test_run_backfill_never_writes_suppression` (stub fails on any `suppression` write); `test_run_backfill_is_idempotent_on_the_unique_key` (`db`, skip when 0018 is not applied, `source_ref 'TEST'`).
- [ ] **Step 2:** Run `uv run pytest -q tests/test_contact_backfill.py`. Expected: FAIL. Implement. Rerun. Expected: pass (the `db` test skipped until the migration).
- [ ] **Step 3:** Commit `feat: contact history backfill parsing`.

### Task 6: The `recontact` pass (Group B)
**Files:** Create `gtm/recontact_pass.py`, `tests/test_recontact_pass.py`.
**Interfaces:** Consumes Tasks 1, 2, 4; `sheet_verify.verify_lead`, `HunterPool`, `tz.lead_tz`, `clean` helpers (`_is_us`, `PLATFORM_DOMAINS`, `SCHOOL_WORDS`). Produces `candidates(db, today) -> list[dict]` (ledger rows that are clear by the Task 2 rule and have no lead with their `history_id`, plus OS leads for which `lead_released` is true and no ledger row of theirs was already re-entered; oldest last send first; `TEST_`/`REHEARSAL_` leads excluded) and `run_recontact(db, pool, limit: int | None, confirm: bool, today: date) -> dict[str, int]`. Dry run: read only, prints eligible count, skips by reason, `0.5 x N` credits and the allowance left, creates nothing. Apply: refuses unless `recontact_on`, `limit` and allowance; creates the batch "Recontact <date>"; per candidate: skip (counted) when the title is not a decision-maker, no usable domain, not US, day spa or school in the name, or a live twin lead; verify through `verify_lead` with bucket `hunter_recontact`; insert the lead in `enriched` (verified) or `no_buyer` (name kept) with `place_id 'recontact:<ledger id>'`, `email_source 'history'`, `round`, `history_id`, `tz`, `batch_id`. An OS candidate first gets a `source 'os'` snapshot ledger row (`outcome no_reply`, `last_sent_on` from its touches). Out of allowance stops the run with `out_of_credits` and leaves the rest untouched.
- [ ] **Step 1:** Failing tests (fake db and fake pool; no network): `test_eligible_pre_os_contact_becomes_an_enriched_lead_when_hunter_says_valid`; `test_failed_verification_saves_a_no_buyer_lead_and_keeps_the_name`; `test_non_decision_maker_title_spends_nothing_and_is_skipped`; `test_dry_run_creates_nothing_spends_nothing_and_prints_cost_and_allowance`; `test_apply_refuses_with_recontact_off`; `test_apply_refuses_without_limit`; `test_apply_with_zero_allowance_raises_before_any_paid_call`; `test_second_run_creates_no_duplicate_lead`; `test_os_sent_lead_gets_a_ledger_snapshot_and_a_round_two_lead_and_the_old_rows_are_untouched`; `test_open_sequence_is_not_a_candidate`; `test_replied_bounced_unsubscribed_and_suppressed_leads_are_never_candidates`; `test_test_and_rehearsal_leads_are_never_candidates`; `test_live_twin_lead_is_skipped_and_counted`; `test_non_us_day_spa_and_no_domain_contacts_are_skipped`; `test_new_lead_is_never_created_cleaned`; `test_cost_rows_use_the_hunter_recontact_bucket`; `test_lead_at_max_rounds_is_not_a_candidate`; `test_candidates_are_oldest_last_send_first`.
- [ ] **Step 2:** Run `uv run pytest -q tests/test_recontact_pass.py`. Expected: FAIL. Implement. Rerun. Expected: pass.
- [ ] **Step 3:** Commit `feat: recontact pass`.

### Task 7: Optional Gmail cross-check (Group B, gated, may be skipped)
**Files:** Create `scripts/history_gmail_check.py`, `tests/test_history_gmail_check.py`.
**Interfaces:** Produces `classify_thread(messages: list[dict], mailbox: str, address: str) -> {"first_out": date | None, "last_out": date | None, "outcome": str}` (pure: any inbound human message is `replied`, a delivery-failure notice naming the address is `bounce`, an auto-reply is `auto_reply`, ambiguous is `replied`, none is `no_reply`) and a read-only `main()` that lists the sending mailbox's messages per ledger address through the existing `gmail_service` and prints counts only. With `--confirm` it may set exact dates and outcomes on ledger rows, but only to a stricter outcome or from `unknown`; it never loosens a row.
- [ ] **Step 1:** Failing tests: `test_inbound_human_message_is_replied`; `test_delivery_failure_naming_the_address_is_bounce`; `test_only_our_messages_is_no_reply_with_exact_dates`; `test_auto_reply_is_auto_reply`; `test_ambiguous_inbound_is_replied`; `test_confirm_never_loosens_an_outcome`.
- [ ] **Step 2:** Run, expect FAIL; implement; rerun, expect pass. Do not run `main()` against the real mailbox (gate 4).
- [ ] **Step 3:** Commit `scripts: history gmail cross-check`.

### Task 8: CLI, worker and autopilot wiring (Group C)
**Files:** Modify `gtm/cli.py`, `gtm/worker.py`; Test `tests/test_cli.py`, `tests/test_worker.py`, `tests/test_autopilot.py`.
**Interfaces:** Produces CLI `recontact [--limit N] [--confirm]` (dry run unless `--confirm`; builds `HunterPool` only when applying) and `backfill-contacts FILE [--sheet] [--confirm]` (dry run unless `--confirm`); `recontact` added to `ALLOWED` in `gtm/worker.py`. `PIPELINE` in `gtm/autopilot.py` is unchanged.
- [ ] **Step 1:** Failing tests: `test_recontact_and_backfill_commands_parse_and_confirm_defaults_false`; `test_recontact_dry_run_builds_no_hunter_pool` (monkeypatch `HunterPool` to raise); `test_recontact_is_an_allowed_worker_kind`; `test_autopilot_never_enqueues_recontact`; `test_autopilot_treats_enriched_recontact_leads_like_any_enriched_lead` (state counts them into the signals stage).
- [ ] **Step 2:** Run the three files, expect FAIL; implement; rerun, expect pass.
- [ ] **Step 3:** Commit `cli: recontact and backfill-contacts`.

### Task 9: Settings block and round label (Group C)
**Files:** Modify `web/app/settings/page.tsx`, `web/lib/runnow.ts`, `web/app/leads/page.tsx`, `web/scripts/runnow_unit.mts`, `web/scripts/verify_runnow.mts`.
- [ ] **Step 1:** Add `"recontact"` to `CONFIRM_KINDS` and to the Jobs dropdown `JOB_KINDS`; a "Recontact" block above Jobs: the four switches through the existing `SettingInput`, a lead-count input, and a `PreviewApply` (`kind "recontact"`, argv `["--limit", N]`, cost text "0.5 Hunter credit per email", `disabledReason` "turn on recontact_on" when off). `/leads` shows "round N" beside the status when `round > 1`.
- [ ] **Step 2:** Failing then passing asserts: `runnow_unit.mts` (`recontact` is a confirm kind; `baseKind("recontact_test") === "recontact"`); `verify_runnow.mts` with kind `recontact_test` (Apply with no preview refused; `enqueueGuarded("recontact_test", ["--limit","5","--confirm"])` refused). Run `cd web && npx tsc --noEmit`, `npx tsx scripts/runnow_unit.mts`, then (autopilot paused) `node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_runnow.mts`. Expected: pass.
- [ ] **Step 3:** Browser check with the owner logged in (Claude-in-Chrome or Playwright): the block renders, Apply is disabled until a Preview, the round label appears on a TEST lead with `round 2`; delete TEST rows. Commit `feat: recontact settings block`.

### Task 10: Parity run, docs, verification (Group D)
**Files:** Create `scripts/recontact_parity.py`; Modify `CLAUDE.md` (Commands and Sending: one bullet each), `docs/HANDOFF.md` section 0, `docs/runbooks/cloud-runner.md` (a short "Recontact" section with the gates).
- [ ] **Step 1:** `scripts/recontact_parity.py` (read-only, counts only): loads real suppression, sent touches and, when migration 0018 exists, the ledger; asserts the flag-off `_blocklists` sets equal the legacy function's; prints, for a simulated flag on (never stored), keys released by reason and ledger rows by outcome and first-eligible week. Run it once against the real database. Expected: parity holds; before 0018 the released count is 0.
- [ ] **Step 2:** Full suite once under the lock, output to a file. Expected: green except `db` tests that need 0018 (skipped, listed in the report).
- [ ] **Step 3:** Edit the three docs; commit `docs: plan 9 status`. One whole-branch review on the most capable model (Review Focus list). Push and deploy only with the owner's yes.

## Hard gates (stop and ask the owner)
1. Applying migration 0018 to the real Supabase project.
2. The real backfill: `backfill-contacts --confirm` (first show the dry-run counts per outcome and eligibility week; it writes only the new table).
3. Reading the sending mailbox for the Gmail cross-check (read-only, owner's yes) and writing its results to the ledger (second yes).
4. Any change to real settings (`recontact_on`, `recontact_days`, `recontact_max_rounds`, `recontact_hunter_allowance_credits`) and any edit, insert or delete of a real `suppression` row. This plan does neither.
5. Any paid call: `recontact` Apply (Hunter), signals, draft, followups, redraft.
6. VM deploy (`deploy.sh`, queue idle; a deploy cancels a running job; deploy with the flag off) and any push.
7. The first real recontact send, and before it the footer decision (opt-out line, postal address) and the email-strategy decision (spec Decision 5). Send stays a separate explicit action.
8. Tests and verify scripts never run `recontact --confirm` or `backfill-contacts --confirm` against the real database and never write the real settings.

## Self-review
Spec coverage: policy and fail-closed core (Tasks 1-3), schema (4), backfill and its date and outcome rules (5), re-entry, identity and twin handling (6), Gmail cross-check (7), CLI, worker, autopilot interplay (8), UI (9), parity, docs, gates (10). Names consistent: `contact_history`, `released_keys`, `lead_released`, `notion_outcome`, `last_sent_bound`, `recontact_on`, `recontact_days`, `recontact_max_rounds`, `recontact_hunter_allowance_credits`, `hunter_recontact`, `history_id`, `round`, `recontact:<ledger id>`. Open owner decisions are in the spec (five); the code ships with everything off and the allowance at 0, so none blocks building.
