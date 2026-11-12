# Scrape and Batches, backend (Plan 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker walks US metros tile by tile (suburb by suburb) on a daily schedule, scrapes and cleans each tile at the cheapest query depth that still finds the places (measured, not guessed), never repeats covered ground, groups selected leads into batches of 100, knows each lead's US time zone, and falls back to Serper or Apify to read a page only when a direct fetch is blocked.

**Architecture:** A `coverage` table holds one row per (metro, state, tile) seeded from a curated CSV. A new `walk` job claims the next pending tile(s), runs the queries one at a time and goes to the next query only when the previous one filled its cap (escalation), reuses `new_batch`, `scrape_city` and `run_clean` unchanged (a tile's scrape run is today's `batches` row), and records the result on the coverage row. The worker loop adds a schedule tick that enqueues one `walk` job a day when enabled in Settings. "Batch of 100" is a number on the lead (`leads.batch_no`) assigned when a lead becomes `selected`, not a new table. The UI pages are Plan 3b.

**Tech Stack:** Python 3.14, Supabase Postgres (migration 0010), existing Apify, Serper, `gtm.budget` and worker modules.

**Spec:** `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` goals 4, 5, 10; sections 11, 15.9. Roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (Plan 3). Measured background: `docs/spikes/apify.md`.

## Global Constraints

- `gtm/config.py` is the only environment reader. Every paid call writes a `cost_log` row and calls `budget.require` first. Never print keys.
- US only, no day spas, lead identity is Google place ID (unique globally). A tile's scrape never touches a known place ID (`scrape_city` already guarantees this).
- Owner decisions 2026-11-12/13: curated CSV of tiles in the repo covering the US metros and their main suburbs; **the daily schedule runs scrape and clean only**; plan split 3a backend / 3b UI; **tile depth is found by measurement, "the sweet spot that costs little but gets the most results on a narrow search"**; **Serper and Apify page fetching run only when a direct fetch is blocked**.
- Measured prices (`docs/spikes/apify.md`): $0.005 per place with the website filter, $0.0061 per on-ICP place for one query of 40, $0.0081 for four queries of 20, about $0.0085 per kept place after cleaning. The tuning spike (Task 1b) replaces guesses with numbers before the defaults are set.
- Daily Apify cap is `cap_apify_usd_day` (default 2.0). The walk stops cleanly at the cap (`BudgetExceeded` becomes job status `paused_budget`).
- Fetch fallback (spec section 11): "No login or captcha bypass". The fallback is an ordinary page read through a paid service with no captcha-solving option enabled; a login wall or captcha page that comes back is treated as a failed fetch.
- "No paid Apify top-up without asking" (HANDOFF f6): every step that spends money needs the owner's yes (Tasks 1b and 8).
- Batches of 100 = verified, selected owners (spec 15.9). A lead's batch is fixed once assigned.
- Tests marked `db` hit the real Supabase project; one pytest process at a time (`mkdir /tmp/gtm-pytest.lock`).
- Parallelism: after Task 1, Tasks 1b, 2-4 (a chain), 5, 6 and 7 are independent of each other and run as parallel agents, each with the ponytail skill. `gtm/cli.py` is edited by Tasks 3, 5, 6 and 7: small hunks only, rebase between agents. `gtm/settings_store.py` is edited by Task 1 first, then by Task 1b (default values only).

## Review Focus

- A tile whose first query returns exactly its cap is probably not exhausted: it must escalate to the next query and, if the last query is also full, be flagged `saturated` rather than silently marked covered. Pinned in Task 3.
- A tile whose first query returns less than the cap is exhausted for that intent: no further paid query runs on it. Pinned in Task 3.
- A walk killed mid-tile (VM reboot, deploy) leaves a `running` tile: it returns to `pending` after 2 hours, and re-scraping is safe because known place IDs are skipped. Pinned in Task 2.
- A budget block releases the claimed tile and leaves no empty scrape batch. Pinned in Task 3.
- The schedule enqueues at most one `walk` per UTC day, even across worker restarts, and nothing while disabled (the default). Pinned in Task 4.
- Selecting more than 100 leads in one run creates several batches; re-running select never renumbers an assigned lead; a partly filled batch is topped up first. Pinned in Task 5.
- Split-time-zone states (El Paso TX, the Florida panhandle, east vs middle Tennessee, western Kentucky, northwest Indiana) and a lead with no state must not crash or return a wrong zone silently (`None` for unknown). Pinned in Task 6.
- Money must not be spent on pages that are simply gone or dead: a 404, 410, DNS failure, timeout, non-HTML or oversize page never triggers the paid fallback; only a block (HTTP 401/403/406/429/503, an anti-bot challenge page, or a page that is an empty JavaScript shell) does. Pinned in Task 7.
- A fallback service returning nothing, an error, or the same challenge page returns `None` like a failed fetch and never raises into a finder, except `BudgetExceeded`, which must propagate. Pinned in Task 7.

---

### Task 1: Migration 0010 and settings defaults

**Files:**
- Create: `supabase/migrations/0010_coverage_batches.sql`
- Modify: `gtm/settings_store.py` (DEFAULTS), `tests/test_settings_store.py`

**Interfaces:**
- Produces: table `coverage(id uuid pk, seq int not null, metro_rank int not null, metro text not null, state text not null, tile text not null, status text not null default 'pending' check in ('pending','running','done','failed'), places_found int, new_leads int, saturated boolean not null default false, queries_run int, scrape_batch_id uuid references batches(id), error text, started_at timestamptz, scraped_at timestamptz, unique (metro, state, tile))` with RLS `operator_only` copied from migration 0007; columns `leads.batch_no int`, `leads.tz text`, index `leads_batch_no_idx`. New DEFAULTS (provisional until Task 1b): `walk_schedule_enabled: False`, `walk_hour_utc: 13`, `walk_tiles_per_run: 3`, `walk_queries: "med spa,aesthetics clinic,botox"` (ordered, comma separated), `walk_max_places: 40` (per query), `walk_escalate_at: 0.9` (go to the next query only when the previous returned at least this fraction of its cap), `fetch_fallback: True`.

- [ ] **Step 1: Failing test** in `tests/test_settings_store.py`: `test_walk_and_fallback_defaults` asserts the seven keys exist in `DEFAULTS` with those values and types, and that `set_setting(db, "walk_hour_utc", True)` raises ValueError (bool is not an int setting; `_ok` already rejects it).
- [ ] **Step 2: Run** `uv run pytest tests/test_settings_store.py -q`. Expected: FAIL (missing keys).
- [ ] **Step 3: Add the DEFAULTS; write the migration.** Owner approves, then apply to the real project with Supabase MCP `apply_migration` (project `KodoAI-GTM-OS`, id `alvxsbnfthvaiquhytig`; additive only).
- [ ] **Step 4: Run** `uv run pytest tests/test_settings_store.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git add supabase/migrations/0010_coverage_batches.sql gtm/settings_store.py tests/test_settings_store.py && git commit -m "feat: coverage table, batch_no and tz columns, walk and fallback settings"`

### Task 1b: Tile tuning spike (owner gate, spends Apify money)

**Files:**
- Create: `scripts/tile_tuning.py`, `docs/spikes/tile_tuning.md`
- Modify: `gtm/settings_store.py` (the three `walk_*` tuning default values only, after the result)

**Interfaces:**
- Consumes: `apify.run_places`, `scrape.scrape_input`, the real clean rule `clean.clean_decision`, `apify.remaining_usd`. Writes nothing to `leads` and creates no batches (dry measurement); each run still writes its `cost_log` row with note `spike:tile_tuning`.
- Produces: `docs/spikes/tile_tuning.md` with a table per tile and per query (places returned, whether the cap was hit, places new versus earlier queries on the same tile and versus `leads`, new places the clean rule keeps, cost, new kept per dollar), and the chosen values for `walk_queries`, `walk_max_places`, `walk_escalate_at` with the reasoning.

- [ ] **Step 1: Choose six tiles** from the metro CSV parts: two dense affluent suburbs (large metro), two mid-size suburbs, two small-town tiles, none from Houston (already covered). Show them to the owner.
- [ ] **Step 2: Write `scripts/tile_tuning.py`** (run as `uv run python -m scripts.tile_tuning`). For each tile it runs the three queries from the recommended set one after another, each at cap 40 with `website: withWebsite`, per-run `maxTotalChargeUsd` 0.50, stopping the tile early when a query returns under its cap (the rule being tested) but still printing what a further query would have yielded only for the first two tiles (to test whether an unfilled first query predicts a useless second). It computes the columns above and prints a table. It must call `budget.require("apify", ...)` before each run.
- [ ] **Step 3 GATE: show the owner the Apify balance (`remaining_usd`), today's spend, and the worst-case cost** (6 tiles x up to 3 queries x 40 places x $0.005 = about $3.60, less when the early-stop rule triggers) and wait for a yes. Then run it.
- [ ] **Step 4: Decide with a stated rule and write the spike doc.** Rule: a further query on a tile is worth running while its new-kept-per-dollar is at least half of the first query's; pick the smallest `walk_max_places` (20, 30 or 40) whose first-query new-kept count is within 10 percent of the 40 result on the same tiles; set `walk_escalate_at` from whether a filled first query predicted a productive second. If the data do not support a rule, say so and keep the provisional defaults.
- [ ] **Step 5: Set the three default values** in `gtm/settings_store.py` to the chosen numbers; run `uv run pytest tests/test_settings_store.py -q`. Expected: PASS (update the Task 1 default assertions to the chosen values).
- [ ] **Step 6: Commit** `git add scripts/tile_tuning.py docs/spikes/tile_tuning.md gtm/settings_store.py tests/test_settings_store.py && git commit -m "spike: tile tuning, measured query depth per tile"`

### Task 2: Coverage seeding

**Files:**
- Create: `gtm/data/metros.csv` (merged from `metros_part1.csv`, `metros_part2.csv`, `metros_part3.csv` written by the data agents, then the parts are deleted), `gtm/coverage.py`
- Test: `tests/test_coverage.py`

**Interfaces:**
- Produces in `gtm/coverage.py`: `load_metros(path: Path = METROS) -> list[dict]` (keys `metro_rank:int, metro, state, tile`, in file order, header `metro_rank,metro,state,tile`); `seed_coverage(db, rows: list[dict]) -> int` (inserts missing rows with `seq` = file position, ignores existing (metro, state, tile), returns the count inserted); `claim_tiles(db, n: int) -> list[dict]` (atomically flips up to n `pending` rows, lowest `seq` first, to `running` with `started_at = now`, returns them); `release_tile(db, tile_id: str) -> None` (back to `pending`); `reset_stale(db, hours: int = 2) -> int` (`running` older than `hours` back to `pending`, returns count).

- [ ] **Step 1: Failing tests** (db-marked, test rows use `metro = "TEST"` and are deleted in a fixture): `test_seed_is_idempotent` (seed 3 rows twice: 3 then 0); `test_claim_takes_lowest_seq_first_and_marks_running`; `test_claim_never_returns_the_same_tile_twice` (two claims of n=2 over 3 tiles return 2 then 1 distinct ids); `test_reset_stale_returns_old_running_tile_to_pending` (set `started_at` 3 h ago, fresh one stays running); plus a no-db `test_csv_has_no_duplicates_and_valid_states` over the real `gtm/data/metros.csv`: header exact, every `state` is a 2-letter US code (50 states + DC), no duplicate (metro, state, tile), each metro has one rank and its first row is its principal city.
- [ ] **Step 2: Run** `uv run pytest tests/test_coverage.py -q`. Expected: FAIL.
- [ ] **Step 3: Merge the three part files** into `gtm/data/metros.csv` ordered by `metro_rank` then original row order. The parts are written from memory (no web lookup) and overlap: Greenville, Albany, Cape Coral, Colorado Springs and Madison appear in parts 2 and 3 with different ranks, so keep each metro's lower rank and drop repeated (metro, state, tile) rows. Fill the gap to the owner's "all US metros": add the metros missing from the Census list of the largest MSAs (at minimum El Paso, Bakersfield, McAllen, Worcester, Allentown, Oxnard, Columbia SC, Little Rock, Stockton, Lakeland, Fayetteville, Augusta, Jackson MS, Mobile, Spokane, Akron, Syracuse, Chattanooga, Lancaster, York, Pensacola, Ogden, Provo, Lexington, Scranton) with 3-8 tiles each, taking ranks from the Census estimates fetched from the web; invent nothing. `.gitignore` carries `!gtm/data/metros*.csv` so the data file is tracked. Delete the parts after the merge. Implement the four functions; `claim_tiles` is a conditional UPDATE per candidate (`.eq("status","pending")` on the id) so a race loses cleanly. `# ponytail: per-row conditional update, fine for one or two workers`.
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/coverage.py gtm/data tests/test_coverage.py .gitignore && git commit -m "feat: coverage seeding from the curated metros CSV"`

### Task 3: The walk pass

**Files:**
- Modify: `gtm/coverage.py`, `gtm/cli.py` (new `walk` and `seed-coverage` commands), `gtm/worker.py` (add `"walk"` to `ALLOWED`)
- Test: `tests/test_walk.py`

**Interfaces:**
- Consumes: Task 2 functions; existing `scrape.new_batch`, `scrape.scrape_city`, `clean.run_clean`, `budget.BudgetExceeded`, `apify.run_places`, settings `walk_queries`, `walk_max_places`, `walk_escalate_at`.
- Produces: `run_walk(db, run_actor, tiles: int, queries: list[str] | None = None, max_places: int | None = None, escalate_at: float | None = None) -> dict` (None means read the setting; `queries` is the ordered list) returning `{"tiles": n, "queries": n, "new": n, "known": n, "saturated": n}`. First `reset_stale`. For each claimed tile: `new_batch(db, tile, state, [queries[0]])`, then for each query in order call `scrape_city(db, wrapped_run_actor, tile, state, [query], batch_id, max_places)` where `wrapped_run_actor` captures the item count; go on to the next query only while the item count of the query just run is `>= escalate_at * max_places`. After the last query, `saturated` is true when that last query also filled its cap. Then `run_clean(db, batch_id)` and set `status='done'`, `places_found` (sum of items), `new_leads`, `saturated`, `queries_run`, `scrape_batch_id`, `scraped_at`. The scrape batch's `query` column gets the queries actually run. `BudgetExceeded`: `release_tile`, re-raise (a tile already partly scraped keeps its leads; known place ids make the rerun safe). Any other exception: tile `failed` with `error`, continue to the next tile. CLI: `gtm walk [--tiles N]` (default `setting("walk_tiles_per_run")`, per-run hard cap `0.50` USD, Apify's minimum) and `gtm seed-coverage` (loads the CSV, prints the inserted count).

- [ ] **Step 1: Failing tests** with a fake `run_actor` returning canned places and the real db with `TEST` coverage rows (db-marked; fake places use ids prefixed `TEST_`, deleted in the fixture): `test_unfilled_first_query_stops_the_tile` (first returns 12 of cap 40: one query run, tile done, not saturated); `test_filled_first_query_escalates_to_the_next` (first returns 40: second query runs); `test_all_queries_filled_marks_saturated`; `test_walk_marks_tile_done_and_records_counts`; `test_walk_budget_block_releases_the_tile_and_creates_no_empty_batch`; `test_walk_failure_marks_failed_and_continues`; no-db `test_walk_is_job_runnable` asserting `"walk" in ALLOWED` and `build_parser().parse_args(["walk", "--tiles", "1"])` parses.
- [ ] **Step 2: Run** `uv run pytest tests/test_walk.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm tests/test_walk.py && git commit -m "feat: walk pass scrapes and cleans the next uncovered tiles with query escalation"`

### Task 4: Daily schedule tick

**Files:**
- Create: `gtm/schedule.py`
- Modify: `gtm/worker.py` (`main` calls the tick each loop)
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces: `tick(db, now: datetime | None = None) -> str | None` returns the new job id when it enqueued a `walk` job (payload `{"argv": ["--tiles", str(setting("walk_tiles_per_run"))]}`) else `None`. It enqueues only when `setting("walk_schedule_enabled")` is true, `now.hour >= setting("walk_hour_utc")` (UTC), and no `walk` job row exists with `created_at >=` UTC midnight today in any status.

- [ ] **Step 1: Failing tests** (db-marked for the job table, settings patched via the existing conftest `setting` patch): `test_disabled_enqueues_nothing`; `test_enabled_before_the_hour_enqueues_nothing`; `test_enabled_after_the_hour_enqueues_once_per_utc_day` (two ticks give one job; a job created yesterday does not block); `test_a_failed_or_cancelled_walk_today_still_blocks_a_second` (no retry storms). Test jobs are marked so the conftest `no_real_jobs` guard holds.
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
- Modify: `gtm/scrape.py` (`place_to_lead` and `SCRAPE_COLUMNS` gain `tz`), `gtm/cli.py` (`tz-backfill`), `tests/test_scrape.py`
- Test: `tests/test_tz.py`

**Interfaces:**
- Produces: `lead_tz(state: str | None, city: str | None) -> str | None` returning an IANA name or `None` for an unknown state. Each state maps to its majority zone (`TX` America/Chicago, `FL` America/New_York, ...). Overrides by lowercase city for split states: El Paso TX -> America/Denver; Pensacola, Destin, Panama City, Fort Walton Beach FL -> America/Chicago; Knoxville, Chattanooga, Johnson City, Kingsport TN -> America/New_York (rest of TN America/Chicago); Bowling Green, Owensboro KY -> America/Chicago (Louisville, Lexington, Covington stay Eastern); Gary, Hammond, Valparaiso, Evansville IN -> America/Chicago; Coeur d'Alene ID -> America/Los_Angeles (Boise stays Mountain); all of AZ -> America/Phoenix; HI -> Pacific/Honolulu; AK -> America/Anchorage. Anything not listed falls back to the state's majority zone.

- [ ] **Step 1: Failing tests** `tests/test_tz.py`: `lead_tz("TX", "Houston") == "America/Chicago"`; `lead_tz("TX", "El Paso") == "America/Denver"`; `lead_tz("FL", "Miami") == "America/New_York"`; `lead_tz("FL", "Pensacola") == "America/Chicago"`; `lead_tz("TN", "Knoxville") == "America/New_York"`; `lead_tz("TN", "Nashville") == "America/Chicago"`; `lead_tz("IN", "Gary") == "America/Chicago"`; `lead_tz("AZ", "Scottsdale") == "America/Phoenix"`; `lead_tz(None, "Houston") is None`; `lead_tz("ZZ", "x") is None`; `lead_tz("tx", " HOUSTON ") == "America/Chicago"` (case and whitespace tolerant). In `tests/test_scrape.py` update the `place_to_lead` column expectation to include `tz`.
- [ ] **Step 2: Run** `uv run pytest tests/test_tz.py tests/test_scrape.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `lead_tz`; add `"tz": lead_tz(item.get("state"), item.get("city"))` to `place_to_lead`; add `tz` to `SCRAPE_COLUMNS`.** Add `gtm tz-backfill` (CLI, free) setting `tz` on existing leads with `tz is null` via `fetch_all` paging.
- [ ] **Step 4: Run** tests. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/tz.py gtm/scrape.py gtm/cli.py tests/test_tz.py tests/test_scrape.py && git commit -m "feat: lead time zone from state and city"`

### Task 7: Page-fetch fallback, only when blocked

**Files:**
- Modify: `gtm/sitescrape.py`, `gtm/search.py` (Serper), `gtm/apify.py`, `gtm/cli.py`, `gtm/enrich.py`, `gtm/signals.py` (production default fetcher only)
- Test: `tests/test_fetch_fallback.py`

**Interfaces:**
- Consumes: existing `http_fetch`, `apify` run loop, `budget.require`, `costs.log_cost`, setting `fetch_fallback`.
- Produces: `sitescrape.fetch_page(url: str) -> tuple[str | None, str]` returning `(text, outcome)` with outcome one of `"ok"`, `"blocked"`, `"gone"`. `blocked` = HTTP 401, 403, 406, 429 or 503; or a 200 page that is an anti-bot challenge (visible text containing a known marker such as "Just a moment", "Attention Required", "captcha", "cf-chl"); or a 200 HTML page with fewer than 200 characters of visible text but script tags (an empty JavaScript shell). `gone` = every other failure (404, 410, DNS failure, timeout, connection reset, non-HTML, oversize). `http_fetch(url)` stays and returns `fetch_page(url)[0]`. `apify.run_actor(actor: str, run_input: dict, max_usd: float) -> tuple[list[dict], float | None]` (the existing `run_places` body generalised; `run_places` calls it with `ACTOR`); `apify.crawl_page(url: str, max_usd: float = 0.05) -> str | None` (actor `apify~website-content-crawler`, one page); `search.serper_scrape(url: str) -> str | None` (Serper's scrape endpoint); `sitescrape.fetch_with_fallback(url: str) -> str | None`: `fetch_page`; when the outcome is `blocked` and `setting("fetch_fallback")` is true, try `serper_scrape` then `crawl_page` (order set by the measured price in Step 1), return the first result with at least 200 characters of text that is not itself a challenge page, else `None`. Cost rows carry the note `fetch-fallback:serper` or `fetch-fallback:apify`. `BudgetExceeded` propagates; every other exception from a fallback service is swallowed (returns `None` for that route).

- [ ] **Step 1: Verify the two services (read-only, free).** Read Serper's scrape endpoint documentation (URL, request body, response field, credits per scrape) and `GET https://api.apify.com/v2/acts/apify~website-content-crawler` (input schema and output text field). Record the exact keys and the per-page price of each in comments in the code and in the PR description; order the fallback cheapest first. **Both are unverified until this step.**
- [ ] **Step 2: Failing tests** (all mocked, no network): `fetch_page` outcome for 200 text, 403, 429, 503, a Cloudflare challenge body, an empty JavaScript shell, 404, 410, a timeout, non-HTML and an oversize body (only the 403, 429, 503, challenge and shell cases are `blocked`); `test_fallback_not_called_when_direct_fetch_works`; `test_fallback_not_called_when_page_is_gone` (404 and timeout cost nothing); `test_fallback_not_called_when_setting_off`; `test_fallback_tries_serper_then_apify_when_blocked`; `test_fallback_rejects_a_challenge_page_from_the_service`; `test_fallback_swallows_service_errors_but_not_budget_exceeded`.
- [ ] **Step 3: Run** `uv run pytest tests/test_fetch_fallback.py -q`. Expected: FAIL.
- [ ] **Step 4: Implement** as specified; replace `http_fetch` with `fetch_with_fallback` in `cmd_enrich` (research finder), as the default of `site_owner_finder` and of `signals.fetch_evidence` (production defaults only; tests keep injecting fakes).
- [ ] **Step 5: Run** `uv run pytest tests/test_fetch_fallback.py tests/test_sitescrape.py tests/test_enrich.py tests/test_signals.py tests/test_search.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `git add gtm tests/test_fetch_fallback.py && git commit -m "feat: Serper and Apify page fetch only when a direct fetch is blocked"`

### Task 8: Live check and docs (owner gates, sequential)

**Files:** `docs/HANDOFF.md`, `CLAUDE.md`, `docs/runbooks/cloud-runner.md`, `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`

- [ ] **Step 1: Seed (free).** `uv run python -m gtm.cli seed-coverage`; report the row and metro counts; `uv run python -m gtm.cli tz-backfill`.
- [ ] **Step 2: Deploy** (queue idle) `bash deploy/deploy.sh gtm-worker us-west1-b`.
- [ ] **Step 3 GATE: one real tile at the tuned depth (about $0.20-0.60).** Show the owner the next pending tile, the tuned settings, and the Apify spend so far today and this month; on yes, enqueue `walk --tiles 1`, watch the job, then verify: coverage row `done` with counts and `queries_run`, a scrape `batches` row, leads `scraped` then `cleaned`, `cost_log` rows for `apify`, no duplicate place ids.
- [ ] **Step 4 GATE: fallback check on blocked sites, about $0.01-0.05.** Take a site whose direct fetch is blocked (Houston measurement: 5 of 41 failed), confirm `fetch_page` says `blocked`, run `fetch_with_fallback` once, and confirm a dead site (404/DNS) triggers nothing. Report the real price per fallback route.
- [ ] **Step 5: Turn the schedule on only if the owner says so** (`walk_schedule_enabled`, Settings). Default stays off.
- [ ] **Step 6: Docs.** HANDOFF section 0 (a)(e)(f), CLAUDE.md commands (`walk`, `seed-coverage`, `tz-backfill`), runbook open items, roadmap row 3a built / 3b open.
- [ ] **Step 7: Commit** `git add docs CLAUDE.md && git commit -m "docs: Plan 3a built, live tile and fallback verified"`

## Self-review

- **Spec coverage:** goal 4 (narrow tiles, metro walk, never repeat covered ground, budget cap) Tasks 1-4 with tile depth set by the Task 1b measurement; goal 5 and 15.9 (batches of 100, fixed once assigned) Task 5; goal 10 retry-later: `enrich --retry-no-buyer` already exists and is job-runnable (`ALLOWED` has `enrich`), so no new code, the Batches page in 3b offers the button; section 11 fetch fallback Task 7 (blocked only, Serper and Apify, no captcha or login bypass); time zone (needed by Plan 4 sending) Task 6; pages Scrape & Coverage and Batches are 3b. Daily schedule runs scrape and clean only (owner decision), enforced because `run_walk` stops after `run_clean`.
- **Skipped on purpose:** sub-tiling of saturated tiles (flagged only), a schedule table (the jobs table already records the last walk), a `lead_batches` table, auto-enrich in the schedule, a coverage map UI, automatic re-tuning. Add when a saturated metro actually blocks yield.
- **Types:** `claim_tiles`, `release_tile`, `reset_stale`, `run_walk`, `tick`, `plan_numbers`, `assign_batches`, `lead_tz`, `fetch_page`, `fetch_with_fallback`, `crawl_page`, `serper_scrape`, `run_actor` are used with the same names and signatures across tasks; the three tuning settings are defined in Task 1, set by Task 1b, read by Task 3.
- **Cost context (unverified economics):** an unfilled first query costs at most $0.20 for a tile; the full three-query escalation costs at most $0.60. At 3 tiles a day that is at most about $1.80 a day and often much less once escalation stops early; the spike gives the real average. The Apify free credit ends 2026-11-24 (HANDOFF f6).
