# Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a worker controller that keeps the current batch of 100 filling (walk, clean, verify, enrich, signals, select, draft) until credit or the owner's USD limit runs out, with Batch03 numbering that matches Notion.

**Architecture:** a pure decision function (`decide`) over a plain state object, a loader that builds that state from the database, and a tick that enqueues at most one existing job per loop. State lives in settings and the jobs table; no migration, no new job kind, no change to the passes.

**Tech Stack:** Python (gtm/), pytest, Next.js for the one UI card.

**Spec:** `docs/superpowers/specs/2026-11-24-autopilot-design.md` (read its "Calls made after the builder check" section: it is part of the spec).

## Global Constraints
- Autopilot never approves a lead, never sends, never sets `sending_on`; it never removes an existing cap.
- Limit is soft: counts every `cost_log.usd` row since `autopilot_started_at`, checked between jobs.
- Existing job statuses: `queued, running, done, failed, cancelled, paused_budget`. Enqueue only kinds already in `gtm/worker.py` ALLOWED.
- A pass runs at most once per (kind, source batch) per run: a `done` job created at or after `autopilot_started_at` counts as tried. `no_buyer` leads are never retried.
- Tests: `TEST_` rows and `TEST` batch names, fake job runners, never real batches, real settings values (restore) or the real mailbox. One pytest at a time: `until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done` ... `rmdir /tmp/gtm-pytest.lock`; long output to a file.
- Every agent: `ponytail:ponytail`, `superpowers:test-driven-development`, graphify before grepping, `superpowers:verification-before-completion`.

## Review Focus
- A pass that leaves leads in the same stage (select with `no_handoff`, enrich with `no_buyer`) must not loop (Task 3).
- Daily cap vs credit: `BudgetExceeded.kind` decides retry-tomorrow versus pause-until-Resume (Tasks 2, 4).
- `select` crossing 100 splits across Batch03 and Batch04 with `batch_base` counted (Task 2).
- Two ticks in a row while a job is queued or running enqueue nothing (Task 3).
- Resume resets the clock and the spend; Pause stops enqueueing but lets the running job finish (Tasks 3, 5).

## Task groups
Task 1 first. Then Tasks 2, 3, 5 in parallel (disjoint files). Then Task 4. Then Task 6.

### Task 1: Settings keys
**Files:** Modify `gtm/settings_store.py`, `web/lib/settings.ts`; Test `tests/test_settings_store.py`, the existing mirror check (`web/scripts/settings_groups.mts`).
**Interfaces:** Produces settings `autopilot_on: bool=False`, `autopilot_limit_usd: float=2.0`, `autopilot_started_at: str=""` (ISO), `autopilot_state: str="off"`, `autopilot_target: int=100`, `batch_base: dict={"3": 32}`. Group name "Autopilot" in `GROUPS`, with `autopilot_state` and `autopilot_started_at` read-only in the UI.
- [ ] Failing test: `test_autopilot_defaults_and_types` (defaults above; a wrong-typed stored `batch_base` falls back to default; `set_setting(db, "autopilot_limit_usd", "x")` raises). Run, expect FAIL. Implement. Run `tests/test_settings_store.py` and `settings_groups.mts`, expect PASS. Commit `settings: autopilot keys`.

### Task 2: Batch numbering with `batch_base`, `BudgetExceeded.kind`, renumber command
**Files:** Modify `gtm/batches.py`, `gtm/budget.py`, `gtm/worker.py` (the `paused_budget` finish only), `gtm/cli.py`; Test `tests/test_batches.py`, `tests/test_budget.py`, `tests/test_worker.py`.
**Interfaces:** Produces
- `plan_numbers(counts: dict[int, int], n_new: int, size: int = BATCH_SIZE) -> list[int]` unchanged signature; `assign_batches(db, lead_ids=None)` now adds `batch_base` (`{"3": 32}`) to the counts before planning (a base batch counts as already used, and the default start batch is the highest base key).
- `BudgetExceeded(message: str, kind: str = "credit")` with `kind` in `daily | credit`; `require` raises `daily` for per-day caps and `credit` for lifetime allowance and Gemini credit.
- worker stores `paused_budget` errors as `"[daily] ..."` or `"[credit] ..."` (prefix from `e.kind`).
- CLI `renumber-batch --from N --to M [--confirm]`: dry run prints how many leads would move; `--confirm` updates `leads.batch_no` only where it equals N and status is `selected`.
- [ ] Failing tests: `test_assign_counts_batch_base` (base 32, 3 new leads without any numbered leads get batch 3, `counts` after = 35); `test_select_crossing_100_rolls_into_next_batch_with_base` (base 98: 5 new leads give 3,3,4,4,4); `test_require_daily_cap_kind_is_daily_and_allowance_kind_is_credit`; `test_paused_budget_error_carries_kind_prefix`; `test_renumber_dry_run_changes_nothing_and_confirm_moves_only_selected` (TEST leads).
- [ ] Run, expect FAIL. Implement. Run those test files, expect PASS. Commit `batches: batch_base, renumber, budget kind`.
- Gate (not part of the task): the real renumbering of the 28 leads is run by the owner's yes after merge.

### Task 3: Controller `gtm/autopilot.py`
**Files:** Create `gtm/autopilot.py`, `tests/test_autopilot.py`.
**Interfaces:** Produces
- `@dataclass AutoState`: `on: bool, paused_reason: str|None, spent_usd: float, limit_usd: float, started_at: str, target: int, open_job: bool, tried: set[tuple[str,str]]  # (kind, batch_id)`, `batches: list[BatchStage]`, `current_fill: int  # numbered leads in the current batch incl. batch_base`, `in_flight: int  # cleaned+enriched+signalled across batches`, `unapproved_selected: int`, `last_budget: tuple[str,str]|None  # (kind, error) of the newest paused_budget job since start`, `recent_failures: int  # consecutive failed pipeline jobs`, `tiles_left: bool`.
- `@dataclass BatchStage`: `batch_id: str, scraped: int, sheet_email_cleaned: int, cleaned: int, enriched: int, signalled: int, approved_undrafted: int`.
- `@dataclass Decision`: `state: str  # running | waiting_approval | paused: <reason>`, `enqueue: tuple[str, list[str]] | None`.
- `decide(s: AutoState) -> Decision` (pure).
- `load_state(db, now) -> AutoState` and `autopilot_tick(db, now=None) -> str | None` (writes `autopilot_state`, enqueues via `gtm.jobs.enqueue`, returns job id).
- `decide` order: off gives state `off`/no job; `open_job` gives no job; `spent_usd >= limit_usd` gives `paused: spend limit`; last budget kind `credit` gives `paused: <error>`; kind `daily` gives no job until the next UTC day (state `paused: daily cap`, retried automatically when `now` is a later UTC day than the job); `recent_failures >= 3` gives `paused: errors`; then the first untried (pass, batch) in the order `clean` (scraped), `verify-sheet --confirm` (sheet_email_cleaned, skipped when the import allowance is spent), `enrich` (cleaned), `signals` (enriched), `select` (signalled), `draft` (approved_undrafted), each with `["--batch", batch_id]`; then `walk` with `["--tiles", walk_tiles_per_run]` only if `current_fill + in_flight < target` and `unapproved_selected < target` and `tiles_left`; `current_fill + in_flight >= target` or `unapproved_selected >= target` gives `waiting_approval`; no tiles gives `paused: no tiles left`.
- [ ] Failing tests in `tests/test_autopilot.py` (pure, no database): one per decision rule above, plus `test_select_that_leaves_signalled_leads_is_not_retried` (tried contains ("select", b): next decision is not select), `test_open_job_enqueues_nothing`, `test_daily_cap_retries_next_utc_day`, `test_credit_pause_stays_until_resume`, `test_walk_not_queued_when_batch_full`, `test_waiting_approval_when_only_unapproved_selected_remain`.
- [ ] Add DB-backed `test_load_state_counts_stages_and_spend` (TEST batch with leads in each stage, `cost_log` rows since and before `started_at`: only after count) and `test_tick_enqueues_one_job_and_writes_state` (kind `clean_test`-style: use a monkeypatched `enqueue`).
- [ ] Run, expect FAIL. Implement. Run `tests/test_autopilot.py`, expect PASS. Commit `autopilot: controller`.

### Task 4: Worker wiring
**Files:** Modify `gtm/worker.py`; Test `tests/test_worker.py`.
**Interfaces:** Consumes `autopilot_tick`. The worker loop's tick list (`walk`, `queue`, `paint`) gains `("autopilot", autopilot_tick)` with its own try block.
- [ ] Failing test: `test_autopilot_tick_runs_after_the_other_ticks_and_survives_their_failure`. Implement the one-line addition. Run `tests/test_worker.py`, expect PASS. Commit `worker: autopilot tick`.

### Task 5: UI card on /batches
**Files:** Modify `web/app/batches/page.tsx`, `web/lib/actions.ts`; Create `web/scripts/verify_autopilot.mts`.
**Interfaces:** Produces `startAutopilot(limitUsd: number): Promise<void>` (sets `autopilot_limit_usd`, `autopilot_started_at` to now, `autopilot_on` true, `autopilot_state` "running") and `pauseAutopilot(): Promise<void>` (sets `autopilot_on` false).
- [ ] Card: state line (`autopilot_state`), spent USD of limit since `autopilot_started_at` (sum of `cost_log.usd`), limit input, Start/Resume and Pause buttons; limit must be greater than 0.
- [ ] `verify_autopilot.mts` under RLS (pattern of `verify_batches.mts`): start sets the three settings, a limit of 0 or negative is refused, pause clears `autopilot_on`; restore the real settings values in `finally`. Run `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_autopilot.mts`; `npx tsc --noEmit`. Expected: ok, no errors. Commit `ui: autopilot card`.

### Task 6: Rehearsal, docs, gates
- [ ] Controller rehearsal on test rows only: a script (`scripts/rehearse_autopilot.py`) with fake runners that moves `TEST_` leads through every stage and prints each decision; expect `waiting_approval` at the end and no real job created.
- [ ] Docs: `CLAUDE.md` Commands (autopilot settings and the card), `docs/HANDOFF.md` section 0.
- [ ] Full suite once under the lock; one fresh whole-branch review on the most capable model; merge.
- **Owner gates (never done by an agent):** the real `renumber-batch --from 1 --to 3 --confirm` (dry run first), deploy to the VM (queue idle), the first real Start with a small limit (for example $2), and funding Apify.

## Self-review
Spec coverage: settings (1), numbering, budget kind, renumber (2), controller rules, limit, approval bound, no-loop rule, sheet verify, draft (3), worker wiring (4), UI Start/Resume/limit (5), rehearsal and gates (6). Types consistent: `AutoState`, `BatchStage`, `Decision`, `BudgetExceeded.kind`, `batch_base` named identically across tasks.
