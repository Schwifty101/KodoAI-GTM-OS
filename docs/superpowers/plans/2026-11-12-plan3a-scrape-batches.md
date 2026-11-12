# Scrape and Batches, backend (Plan 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker walks US metros tile by tile (suburb by suburb) on a daily schedule, scrapes and cleans each tile inside the Apify budget, never repeats covered ground, groups selected leads into batches of 100, knows each lead's US time zone, and can fall back to Apify when a direct page fetch fails.

**Architecture:** A `coverage` table holds one row per (metro, state, tile) seeded from a curated CSV. A new `walk` job claims the next pending tile(s), reuses the existing `new_batch` + `scrape_city` + `run_clean` unchanged (a tile's scrape run is today's `batches` row), and records the result on the coverage row. The worker loop adds a schedule tick that enqueues one `walk` job a day when enabled in Settings. "Batch of 100" is a number on the lead (`leads.batch_no`) assigned when a lead becomes `selected`, not a new table. The UI pages are Plan 3b.

**Tech Stack:** Python 3.14, Supabase Postgres (migration 0010), existing Apify, `gtm.budget` and worker modules.

**Spec:** `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` goals 4, 5, 10; sections 11, 15.9. Roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (Plan 3). Measured background: `docs/spikes/apify.md`.

## Global Constraints

- `gtm/config.py` is the only environment reader. Every paid call writes a `cost_log` row and calls `budget.require` first. Never print keys.
- US only, no day spas, lead identity is Google place ID (unique globally). A tile's scrape never touches a known place ID (`scrape_city` already guarantees this).
- Owner decisions 2026-11-12: curated CSV of tiles in the repo covering the US metros and their main suburbs; **the daily schedule runs scrape and clean only**; enrich, signals and select stay a button press; plan split 3a backend / 3b UI.
- Daily Apify cap is `cap_apify_usd_day` (default 2.0). A tile with 3 queries x 40 places costs about $0.60 at the listed price (`docs/spikes/apify.md`), so about 3 tiles a day fit. The walk must stop cleanly at the cap (`BudgetExceeded` becomes job status `paused_budget`).
- "No paid Apify top-up without asking" (HANDOFF f6): Task 8 steps that spend money need the owner's yes.
- Batches of 100 = verified, selected owners (spec 15.9). A lead's batch is fixed once assigned.
- Tests marked `db` hit the real Supabase project; one pytest process at a time (`mkdir /tmp/gtm-pytest.lock`).
- Parallelism: after Task 1, Tasks 2-4 are a chain; Tasks 5, 6 and 7 are independent of it and of each other and can run as parallel agents. `gtm/cli.py` is edited by Tasks 3, 5 and 7: do those edits one at a time (rebase between agents), small hunks only.

## Review Focus

- A tile whose scrape returns the cap (every query full) is probably not exhausted: it must be flagged `saturated`, not silently marked covered. Pinned in Task 3.
- A walk killed mid-tile (VM reboot, deploy) leaves a `running` tile: it must return to `pending` after 2 hours, and re-scraping is safe because known place IDs are skipped. Pinned in Task 2.
- A budget block must release the claimed tile and leave no empty scrape batch. Pinned in Task 3.
- The schedule must enqueue at most one `walk` per UTC day, even across worker restarts, and nothing while disabled (the default). Pinned in Task 4.
- Selecting more than 100 leads in one run must create several batches; re-running select must never renumber an assigned lead; a partly filled batch is topped up first. Pinned in Task 5.
- Split-time-zone states (El Paso TX, the Florida panhandle, east vs middle Tennessee, western Kentucky, northwest Indiana) and a lead with no state must not crash or return a wrong zone silently (`None` for unknown). Pinned in Task 6.
- Apify returning nothing or an actor error for the fallback must return `None` like a failed fetch, never raise into a finder. Pinned in Task 7.

---

### Task 1: Migration 0010 and settings defaults

**Files:**
- Create: `supabase/migrations/0010_coverage_batches.sql`
- Modify: `gtm/settings_store.py` (DEFAULTS), `tests/test_settings_store.py`

**Interfaces:**
- Produces: table `coverage(id uuid pk, seq int not null, metro_rank int not null, metro text not null, state text not null, tile text not null, status text not null default 'pending' check in ('pending','running','done','failed'), places_found int, new_leads int, saturated boolean not null default false, scrape_batch_id uuid references batches(id), error text, started_at timestamptz, scraped_at timestamptz, unique (metro, state, tile))` with RLS `operator_only` copied from migration 0007; columns `leads.batch_no int`, `leads.tz text`, index `leads_batch_no_idx`. New DEFAULTS: `walk_schedule_enabled: False`, `walk_hour_utc: 13`, `walk_tiles_per_run: 3`, `apify_fetch_fallback: False`.

- [ ] **Step 1: Failing test** in `tests/test_settings_store.py`: `test_walk_and_fallback_defaults` asserts the four new keys exist in `DEFAULTS` with those values and types, and that `set_setting(db, "walk_hour_utc", True)` raises ValueError (bool is not an int setting; `_ok` already rejects it).
- [ ] **Step 2: Run** `uv run pytest tests/test_settings_store.py -q`. Expected: FAIL (missing keys).
- [ ] **Step 3: Add the four DEFAULTS; write the migration.** Owner approves, then apply to the real project with Supabase MCP `apply_migration` (project `KodoAI-GTM-OS`, id `alvxsbnfthvaiquhytig`; additive only).
- [ ] **Step 4: Run** `uv run pytest tests/test_settings_store.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git add supabase/migrations/0010_coverage_batches.sql gtm/settings_store.py tests/test_settings_store.py && git commit -m "feat: coverage table, batch_no and tz columns, walk and fallback settings"`

### Task 2: Coverage seeding

**Files:**
- Create: `gtm/data/metros.csv` (merged from `metros_part1.csv`, `metros_part2.csv`, `metros_part3.csv` written by the data agents, then the parts are deleted), `gtm/coverage.py`
- Test: `tests/test_coverage.py`

**Interfaces:**
- Produces in `gtm/coverage.py`: `load_metros(path: Path = METROS) -> list[dict]` (keys `metro_rank:int, metro, state, tile`, in file order, header `metro_rank,metro,state,tile`); `seed_coverage(db, rows: list[dict]) -> int` (inserts missing rows with `seq` = file position, ignores existing (metro, state, tile), returns the count inserted); `claim_tiles(db, n: int) -> list[dict]` (atomically flips up to n `pending` rows, lowest `seq` first, to `running` with `started_at = now`, returns them); `release_tile(db, tile_id: str) -> None` (back to `pending`); `reset_stale(db, hours: int = 2) -> int` (`running` older than `hours` back to `pending`, returns count).

- [ ] **Step 1: Failing tests** (db-marked, test rows use `metro = "TEST"` and are deleted in a fixture): `test_seed_is_idempotent` (seed 3 rows twice: 3 then 0); `test_claim_takes_lowest_seq_first_and_marks_running`; `test_claim_never_returns_the_same_tile_twice` (two claims of n=2 over 3 tiles return 2 then 1 distinct ids); `test_reset_stale_returns_old_running_tile_to_pending` (set `started_at` 3 h ago, fresh one stays running); plus a no-db test `test_csv_has_no_duplicates_and_valid_states` over the real `gtm/data/metros.csv`: header exact, every `state` is a 2-letter US code (50 states + DC), no duplicate (metro, state, tile), every metro's first row is its principal city (rank constant per metro).
- [ ] **Step 2: Run** `uv run pytest tests/test_coverage.py -q`. Expected: FAIL.
- [ ] **Step 3: Merge the three part files** into `gtm/data/metros.csv` ordered by `metro_rank` then original row order; the parts are written from memory (no web lookup) and overlap: Greenville, Albany, Cape Coral, Colorado Springs and Madison appear in parts 2 and 3 with different ranks, so keep each metro's lower rank and drop repeated (metro, state, tile) rows. Fill the gap to the owner's "all US metros": add the metros missing from the Census list of the largest MSAs (at minimum El Paso, Bakersfield, McAllen, Worcester, Allentown, Oxnard, Columbia SC, Little Rock, Stockton, Lakeland, Fayetteville, Augusta, Jackson MS, Mobile, Spokane, Akron, Syracuse, Chattanooga, Lancaster, York, Pensacola, Ogden, Provo, Lexington, Scranton) with 3-8 tiles each, taking ranks from the Census estimates fetched from the web; mark nothing invented. `.gitignore` carries `!gtm/data/metros*.csv` so the data file is tracked. Delete the parts after the merge. Implement the four functions; `claim_tiles` is a conditional UPDATE per candidate (`.eq("status","pending")` on the id) so a race loses cleanly. `# ponytail: per-row conditional update, fine for one or two workers`.
- [ ] **Step 4: Run** tests. Expected: PASS (and the CSV test lists no duplicates).
- [ ] **Step 5: Commit** `git add gtm/coverage.py gtm/data tests/test_coverage.py && git commit -m "feat: coverage seeding from the curated metros CSV"`

### Task 3: The walk pass

**Files:**
- Modify: `gtm/coverage.py`, `gtm/cli.py` (new `walk` and `seed-coverage` commands), `gtm/worker.py` (add `"walk"` to `ALLOWED`)
- Test: `tests/test_walk.py`

**Interfaces:**
- Consumes: Task 2 functions; existing `scrape.new_batch`, `scrape.scrape_city`, `clean.run_clean`, `budget.BudgetExceeded`, `apify.run_places`.
- Produces: `run_walk(db, run_actor, tiles: int, queries: list[str] = DEFAULT_QUERIES, max_places: int = 40) -> dict` returning `{"tiles": n, "new": n, "known": n, "saturated": n}`. For each claimed tile: `new_batch(db, tile, state, queries)`, `scrape_city(...)` with `run_actor` wrapped to capture the item count, `run_clean(db, batch_id)`, then set `status='done'`, `places_found`, `new_leads`, `saturated`, `scrape_batch_id`, `scraped_at`. Saturated = item count >= `max_places * len(queries)` (every query hit its cap; `# ponytail: proxy for "tile not exhausted", sub-tiling is a later job`). `BudgetExceeded`: call `release_tile`, re-raise. Any other exception: tile `failed` with `error`, continue to the next tile. `run_walk` calls `reset_stale` first. CLI: `gtm walk [--tiles N]` (default `setting("walk_tiles_per_run")`, per-tile hard cap `0.75` USD) and `gtm seed-coverage` (loads the CSV, prints the inserted count).

- [ ] **Step 1: Failing tests** with a fake `run_actor` returning canned places and the real db with `TEST` coverage rows (db-marked): `test_walk_marks_tile_done_and_records_counts`; `test_walk_flags_a_full_tile_saturated` (fake returns exactly 120 items for 3 queries x 40); `test_walk_budget_block_releases_the_tile_and_creates_no_batch` (fake raises `BudgetExceeded` on the first call: tile back to `pending`, no `batches` row for it, the exception propagates); `test_walk_failure_marks_failed_and_continues` (first tile raises RuntimeError, second succeeds); no-db `test_walk_is_job_runnable` asserting `"walk" in ALLOWED` and `build_parser().parse_args(["walk", "--tiles", "1"])` parses.
- [ ] **Step 2: Run** `uv run pytest tests/test_walk.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Test leads created by the fake must be deleted in the fixture (place ids prefixed `TEST_`).
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm tests/test_walk.py && git commit -m "feat: walk pass scrapes and cleans the next uncovered tiles"`

### Task 4: Daily schedule tick

**Files:**
- Create: `gtm/schedule.py`
- Modify: `gtm/worker.py` (`main` calls the tick each loop)
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces: `tick(db, now: datetime | None = None) -> str | None` returns the new job id when it enqueued a `walk` job (payload `{"argv": ["--tiles", str(setting("walk_tiles_per_run"))]}`) else `None`. It enqueues only when `setting("walk_schedule_enabled")` is true, `now.hour >= setting("walk_hour_utc")` (UTC), and no `walk` job row exists with `created_at >=` UTC midnight today in any status.

- [ ] **Step 1: Failing tests** (db-marked for the job table, settings patched via the existing conftest `setting` patch): `test_disabled_enqueues_nothing`; `test_enabled_before_the_hour_enqueues_nothing`; `test_enabled_after_the_hour_enqueues_once_per_utc_day` (two ticks give one job; a job created yesterday does not block); `test_a_failed_or_cancelled_walk_today_still_blocks_a_second` (no retry storms). Test jobs carry `payload {"test": 1}`-style marking via a patched enqueue wrapper so the `no_real_jobs` guard in conftest holds.
- [ ] **Step 2: Run** `uv run pytest tests/test_schedule.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `tick`; call it from `worker.main` before each `run_one`** (wrapped in try/except so a tick error never stops the loop; log with `print`).
- [ ] **Step 4: Run** `uv run pytest tests/test_schedule.py tests/test_worker.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/schedule.py gtm/worker.py tests/test_schedule.py && git commit -m "feat: worker enqueues one walk job a day when the schedule is on"`

### Task 5: Batches of 100

**Files:**
- Create: `gtm/batches.py`
- Modify: `gtm/cli.py` (`cmd_select` calls it after `run_select`)
- Test: `tests/test_batches.py`

**Interfaces:**
- Produces: `BATCH_SIZE = 100`; pure `plan_numbers(counts: dict[int, int], n_new: int, size: int = BATCH_SIZE) -> list[int]` (given current lead counts per batch number, returns the batch number for each of `n_new` new leads: top up the highest-numbered batch if under `size`, then open the next numbers; empty `counts` starts at 1); `assign_batches(db) -> int` (selects leads with `status = 'selected'` and `batch_no is null` ordered by `created_at, id`, counts existing numbered leads per `batch_no`, writes the numbers, returns the count assigned; never touches a lead that already has a `batch_no`).

- [ ] **Step 1: Failing tests** (no db): `plan_numbers({}, 3) == [1,1,1]`; `plan_numbers({1: 98}, 5) == [1,1,2,2,2]`; `plan_numbers({1: 100}, 1) == [2]`; `plan_numbers({1: 100, 2: 40}, 70) == [2]*60 + [3]*10`; `plan_numbers({1: 50}, 0) == []`. One db-marked test `test_assign_is_stable_on_rerun`: two TEST selected leads get batch numbers, a second `assign_batches` returns 0 and changes nothing.
- [ ] **Step 2: Run** `uv run pytest tests/test_batches.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Batch counting reads every numbered lead through `fetch_all` (1000-row page cap, see `gtm/db.py`). `# ponytail: two concurrent selects could race on the same batch; one worker runs selects serially`.
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/batches.py gtm/cli.py tests/test_batches.py && git commit -m "feat: selected leads are numbered into batches of 100"`

### Task 6: Lead time zone

**Files:**
- Create: `gtm/tz.py`
- Modify: `gtm/scrape.py` (`place_to_lead` and `SCRAPE_COLUMNS` gain `tz`), `tests/test_scrape.py`
- Test: `tests/test_tz.py`

**Interfaces:**
- Produces: `lead_tz(state: str | None, city: str | None) -> str | None` returning an IANA name or `None` for an unknown state. Each state maps to its majority zone (`TX` America/Chicago, `FL` America/New_York, ...). Overrides by lowercase city for split states: El Paso TX and Hudspeth County seats -> America/Denver; Pensacola, Destin, Panama City, Fort Walton Beach FL -> America/Chicago; Knoxville, Chattanooga, Johnson City, Kingsport TN -> America/New_York (rest of TN America/Chicago); Bowling Green, Owensboro KY -> America/Chicago (Louisville, Lexington, Covington stay Eastern); Gary, Hammond, Valparaiso, Evansville IN -> America/Chicago; Boise stays Mountain, north Idaho (Coeur d'Alene) -> America/Los_Angeles; Phoenix and AZ -> America/Phoenix; HI -> Pacific/Honolulu; AK -> America/Anchorage. Anything not listed falls back to the state's majority zone.

- [ ] **Step 1: Failing tests** `tests/test_tz.py`: `lead_tz("TX", "Houston") == "America/Chicago"`; `lead_tz("TX", "El Paso") == "America/Denver"`; `lead_tz("FL", "Miami") == "America/New_York"`; `lead_tz("FL", "Pensacola") == "America/Chicago"`; `lead_tz("TN", "Knoxville") == "America/New_York"`; `lead_tz("TN", "Nashville") == "America/Chicago"`; `lead_tz("IN", "Gary") == "America/Chicago"`; `lead_tz("AZ", "Scottsdale") == "America/Phoenix"`; `lead_tz(None, "Houston") is None`; `lead_tz("ZZ", "x") is None`; `lead_tz("tx", " HOUSTON ") == "America/Chicago"` (case and whitespace tolerant). In `tests/test_scrape.py` update the `place_to_lead` column expectation to include `tz`.
- [ ] **Step 2: Run** `uv run pytest tests/test_tz.py tests/test_scrape.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `lead_tz`; add `"tz": lead_tz(item.get("state"), item.get("city"))` to `place_to_lead`; add `tz` to `SCRAPE_COLUMNS`.** Add `gtm tz-backfill` (CLI, free) setting `tz` on existing leads with `tz is null` via `fetch_all` paging.
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/tz.py gtm/scrape.py gtm/cli.py tests/test_tz.py tests/test_scrape.py && git commit -m "feat: lead time zone from state and city"`

### Task 7: Apify page-fetch fallback

**Files:**
- Modify: `gtm/apify.py`, `gtm/sitescrape.py`, `gtm/cli.py` (use the new fetcher where `http_fetch` is passed)
- Test: `tests/test_apify_fetch.py`

**Interfaces:**
- Consumes: existing `apify.run_places` run loop, `budget.require`, `costs.log_cost`, setting `apify_fetch_fallback`.
- Produces: `apify.run_actor(actor: str, run_input: dict, max_usd: float) -> tuple[list[dict], float | None]` (the existing `run_places` body generalised; `run_places(run_input, max_usd)` calls it with `ACTOR`); `apify.crawl_page(url: str, max_usd: float = 0.05) -> str | None` (actor `apify~website-content-crawler`, one page, returns the page text or `None` on no items or any error; logs cost); `sitescrape.fetch_with_fallback(url: str) -> str | None` (`http_fetch(url)`, and only if that is `None` and `setting("apify_fetch_fallback")` is true, `crawl_page(url)`).

- [ ] **Step 1: Verify the actor (read-only, free).** `GET https://api.apify.com/v2/acts/apify~website-content-crawler` and read its input schema; record the exact input keys used (`startUrls`, `maxCrawlPages`, ...) and output text field in a comment in `apify.py`. **Unverified until this step.**
- [ ] **Step 2: Failing tests** (mock `run_actor`): `test_crawl_page_returns_text`; `test_crawl_page_returns_none_when_no_items`; `test_crawl_page_swallows_actor_errors` (except `BudgetExceeded`, which must propagate so the job pauses); `test_fallback_not_called_when_setting_off`; `test_fallback_not_called_when_direct_fetch_works`; `test_fallback_used_when_direct_fetch_fails_and_setting_on`.
- [ ] **Step 3: Run** `uv run pytest tests/test_apify_fetch.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** as specified; replace `http_fetch` with `fetch_with_fallback` in `cmd_enrich` (research finder), `site_owner_finder` default and `signals.fetch_evidence` default arguments only where they are the production default.
- [ ] **Step 5: Run** `uv run pytest tests/test_apify_fetch.py tests/test_sitescrape.py tests/test_enrich.py tests/test_signals.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `git add gtm tests/test_apify_fetch.py && git commit -m "feat: optional Apify fallback when a direct page fetch fails"`

### Task 8: Live check and docs (owner gates, sequential)

**Files:** `docs/HANDOFF.md`, `CLAUDE.md`, `docs/runbooks/cloud-runner.md`, `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`

- [ ] **Step 1: Seed (free).** `uv run python -m gtm.cli seed-coverage`; report the row and metro counts; `uv run python -m gtm.cli tz-backfill`.
- [ ] **Step 2: Deploy** (queue idle) `bash deploy/deploy.sh gtm-worker us-west1-b`.
- [ ] **Step 3 GATE: one real tile, about $0.60.** Show the owner the next pending tile and the Apify spend so far today and this month; on yes, enqueue `walk --tiles 1`, watch the job, then verify: coverage row `done` with counts, a scrape `batches` row, leads `scraped` then `cleaned`, a `cost_log` row for `apify`, no duplicate place ids.
- [ ] **Step 4 GATE: apify fetch fallback spike, about $0.01.** On one site where a direct fetch fails, with `apify_fetch_fallback` on, confirm text comes back; turn the setting back off unless the owner wants it on.
- [ ] **Step 5: Turn the schedule on only if the owner says so** (`walk_schedule_enabled`, Settings). Default stays off.
- [ ] **Step 6: Docs.** HANDOFF section 0 (a)(e)(f), CLAUDE.md commands (`walk`, `seed-coverage`, `tz-backfill`), runbook open items, roadmap row 3a built / 3b open.
- [ ] **Step 7: Commit** `git add docs CLAUDE.md && git commit -m "docs: Plan 3a built, live tile verified"`

## Self-review

- **Spec coverage:** goal 4 (narrow tiles, metro walk, never repeat covered ground, budget cap) Tasks 1-4; goal 5 and 15.9 (batches of 100, fixed once assigned) Task 5; goal 10 retry-later: `enrich --retry-no-buyer` already exists and is job-runnable (`ALLOWED` has `enrich`), so no new code, the Batches page in 3b offers the button; section 11 fetch fallback Task 7; time zone (needed by Plan 4 sending) Task 6; pages Scrape & Coverage and Batches are 3b. Daily schedule runs scrape and clean only (owner decision), enforced because `run_walk` stops after `run_clean`.
- **Skipped on purpose:** sub-tiling of saturated tiles (flagged only), a schedule table (the jobs table already records the last walk), a `lead_batches` table, auto-enrich in the schedule, a coverage map UI. Add when a saturated metro actually blocks yield.
- **Types:** `claim_tiles`, `release_tile`, `reset_stale`, `run_walk`, `tick`, `plan_numbers`, `assign_batches`, `lead_tz`, `crawl_page`, `fetch_with_fallback`, `run_actor` are used with the same names and signatures across tasks.
- **Cost context (unverified economics):** about 15 tiles a week at $0.60 is about $9 a week (about $40 a month, about 11,000 PKR, about 40 percent of the monthly budget); the Apify free credit ends 2026-11-24 (HANDOFF f6). The weekly target is a Settings value and the daily Apify cap is the brake.
