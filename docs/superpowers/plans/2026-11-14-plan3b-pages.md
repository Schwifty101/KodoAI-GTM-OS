# Scrape & Coverage and Batches Pages (Plan 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new browser pages (Scrape & Coverage, Batches), the walk settings editable in the UI, a "retry later" button for known-owner leads whose email could not be verified, and Settings page copy that matches the system as it now is.

**Architecture:** The pages are client components in the existing style (`useRequireSession`, `supabase-js` with the publishable key under operator RLS, writes only through `web/lib/actions.ts`). They never run a pass: every paid action inserts a `jobs` row through `enqueueJob`, and the VM worker runs it. Data loading lives in small `lib/` functions that both the page and `scripts/verify.mts`-style checks call, so the queries are verified against the real database without a browser. One additive migration (a view for spend per batch of 100) and one small Python flag (`--named-only`) are the only non-UI changes.

**Tech Stack:** Next.js 16 (App Router, client components), `@supabase/supabase-js` 2.119, TypeScript, `tsx` for verify scripts. No new libraries. Python 3.14 + pytest for the one backend flag.

**Spec:** `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` section 2 (goals 4, 5), section 5 (Pages: Batches, Scrape & Coverage), section 11 (retry later, waste buckets), section 15.9 (batches of 100). Roadmap row 3: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`. Built backend: `docs/superpowers/plans/2026-11-12-plan3a-scrape-batches.md`. Measured defaults: `docs/spikes/tile_tuning.md`.

## Owner's question: do these four pending items belong to Plan 3b?

| Item | In Plan 3b? | Answer |
|---|---|---|
| (a) Scrape & Coverage and Batches pages | **Yes** | Tasks 4 and 5 (plus the shared groundwork in Task 1). |
| (b) Retry-later for known-owner / unverified-email leads | **Yes, button plus one small backend flag** | The job exists: `enrich --retry-no-buyer` is job-runnable (`ALLOWED` in `gtm/worker.py` contains `enrich`). Reading `gtm/enrich.py` shows it is not enough on its own: `run_enrich(..., retry_no_buyer=True)` re-runs **every** `no_buyer` lead of the batch, including those with no name at all, so it would re-spend the Gemini research step and credits on the "no owner found" bucket that spec section 11 says is parked. Spec section 11 says retry only the named-but-no-email leads. Task 2 adds `--named-only` (3 lines + a test); Task 5 adds the button. Nothing else is needed: a saved email is already kept (`source: "saved"`), and running out of Hunter or Prospeo credits already stops the loop cleanly (`OutOfCredits`) and leaves the remaining leads `no_buyer`. The spec's "monthly job" is not built: owner decision here is a manual button, never automatic (a monthly schedule can be a later one-liner on the walk schedule pattern). |
| (c) Full suite rerun after Plan 3 review fixes | **No, done** | 589 passed, 0 failed, 0 skipped on 2026-11-13 (the earlier 573 passed / 1 failed was the live VM worker taking a test's job, fixed by migration 0011). Plan 3b only adds one pytest (Task 2) and verify scripts. |
| (d) Integration of the Plan 3 branch with latest main incl. Flash-Lite | **No, done** | PR #4 merged; `main` contains the Flash-Lite commit `330e62d` (REPLY_MODEL `gemini-3.1-flash-lite`, `gemini_lite_*` price settings). A suite run on merged `main` is in progress (reported by the coordinator, not by this plan). Plan 3b only picks up the consequence: the two `gemini_lite_*` keys must appear in the web settings list (Task 1). |

## Global Constraints

- The UI never runs passes and never holds the secret key. `Supabase secret key is script-side only, never in the browser` (CLAUDE.md). Writes go through `web/lib/actions.ts` (verify scripts exercise the same calls under RLS).
- The daily schedule is OFF by owner decision (`walk_schedule_enabled` default `False`); only the owner turns it on. The pages say so and never flip it themselves.
- Every paid action is an explicit click that enqueues a job. No page load, effect or timer enqueues anything. A paid button warns what it spends and is disabled while an identical job is open.
- "Send is always a separate explicit action": no send button, no draft page here (Plan 4).
- Settings keys and types mirror `DEFAULTS` in `gtm/settings_store.py` (now 25 keys, including `gemini_lite_input_usd_per_m`, `gemini_lite_output_usd_per_m`, `walk_schedule_enabled`, `walk_hour_utc`, `walk_tiles_per_run`, `walk_queries`, `walk_max_places`, `walk_escalate_at`, `fetch_fallback`).
- Statuses and coverage states exactly as the schema: coverage `pending|running|done|failed`; leads `scraped, cleaned/rejected, enriched/no_buyer, signalled, selected, drafted, sent, replied, booked`, side states `bounced, suppressed, unsubscribed`.
- Batch of 100 = leads with `batch_no` set (assigned when a lead becomes `selected`, spec 15.9); a lead's batch is fixed. Scrape run = today's `batches` row (one per tile walked).
- Ponytail: no new dependency, no charts library (a CSS-width bar), no state library, no table component. Copy the existing `.card`, `.grid`, `.bar`, `.pill`, `table` classes in `web/app/globals.css`.
- Tests marked `db` hit the real Supabase project; one pytest process at a time (`mkdir /tmp/gtm-pytest.lock`). Verify scripts clean up their `TEST` rows.
- Parallelism: Task 1 first. Then Tasks 2, 3 and 4 are independent (parallel agents). Task 5 needs Tasks 1, 2, 3. Task 6 last. Tasks 4 and 5 both touch `web/app/layout.tsx` only in Task 1, so they do not collide. Each task owns its own verify script, so no shared-file conflicts.

## Review Focus

- Double click, or a second tab, on "Run N tiles now" or "Retry later" while an identical job is queued, running or paused for budget must not enqueue a second paid job. Pinned in Task 1 (`enqueueJobOnce`) and used by Tasks 4 and 5.
- "Retry later" on a scrape run with zero named `no_buyer` leads is disabled and enqueues nothing; on a run whose leads are mixed it retries only the named ones. Pinned in Tasks 2 and 5.
- Retrying a tile must only flip `failed` to `pending`; a `running` tile (a worker is on it) or `done` tile (already paid for) is never touched. Pinned in Task 4.
- Bad setting input must be rejected before saving: empty `walk_queries` (the walk would index `queries[0]` of an empty list), `walk_hour_utc` outside 0-23, `walk_escalate_at` outside 0-1, `walk_tiles_per_run` or the "N tiles" box of 0 or huge (a `--tiles 0` silently means "use the setting"). Pinned in Tasks 1 and 4.
- More than 1000 coverage rows (1285 are seeded) and more than 1000 leads must be read completely (PostgREST caps a request at 1000): totals must equal a `count: exact` head query. Pinned in Tasks 4 and 5.
- Apify day cap at 0 or already reached: the page shows "blocked / at cap" and the Run button warns instead of letting the worker pause the job silently. Pinned in Task 4.
- Empty states (no coverage, no batch numbers yet, no failed tiles, nothing to retry) render a plain sentence, not a crash or a `NaN%`. Pinned by the manual checklists.

---

### Task 1: Shared groundwork (settings fields, hooks, actions, nav)

**Files:**
- Modify: `web/lib/settings.ts`, `web/lib/actions.ts`, `web/lib/types.ts`, `web/app/layout.tsx`, `web/app/settings/page.tsx`, `web/scripts/verify.mts`, `web/app/globals.css` (only if a bar class is needed, see Task 4)
- Create: `web/lib/useSettings.ts`, `web/components/SettingInput.tsx`

**Interfaces:**
- Produces in `lib/settings.ts`: `SettingField = { key; label; type: "int"|"float"|"bool"|"date"|"text"; group; def: boolean|number|string; min?: number; max?: number }`. `SETTING_FIELDS` now holds all 25 keys, each with its `def` (the default shown when no row is stored), groups `Budget`, `Google credit`, `API prices`, `Daily caps`, `Scrape walk`, `Page fetching`. The duplicate `DEFAULTS` object in `app/settings/page.tsx` is deleted. `validSetting(f, v)` additionally enforces `min`/`max` for numbers and non-empty trimmed string for `text`. `settingDefaults(): Record<string, unknown>` returns `{key: def}`.
- Produces in `lib/useSettings.ts`: `useSettings(ready: boolean): { vals: Record<string, unknown>; reload: () => Promise<void>; save: (f: SettingField, raw: string | boolean) => Promise<void>; err: string }`. Loads the `settings` table over `settingDefaults()`; `save` converts numeric text to a number (empty becomes `NaN`, which `validSetting` rejects), calls `saveSetting`, reloads, and puts a rejection message in `err`.
- Produces `components/SettingInput.tsx`: `SettingInput({ f, vals, save })` renders one setting card exactly as the current `field()` in the Settings page does (uncontrolled input remounted by `key` after a save; checkbox for bool; `type="text"` for text).
- Produces in `lib/actions.ts`: `enqueueJobOnce(kind: string, argv: string[]): Promise<void>` throws `Error("an identical job is already open")` when a `jobs` row with the same `kind`, `payload.argv` equal, and status in `queued, running, paused_budget` exists; otherwise calls `enqueueJob`. `retryTile(id: string): Promise<void>` sets `coverage` `status: "pending", error: null` where `id` matches and `status = "failed"`. Types `Coverage`, `Lead` additions in `lib/types.ts`: `Coverage = { id; seq; metro_rank; metro; state; tile; status: "pending"|"running"|"done"|"failed"; places_found: number|null; new_leads: number|null; saturated: boolean; queries_run: number|null; scrape_batch_id: string|null; error: string|null; started_at: string|null; scraped_at: string|null }`; `Lead` gains `batch_no: number | null; tz: string | null`; `LEAD_COLUMNS` gains `batch_no,tz`.

- [ ] **Step 1: Failing checks** in `web/scripts/verify.mts` (replace the `pyKeys.length === 16` assertion, which is already stale, with a comparison against the live Python defaults). Add, before the cleanup block:
  - `check("SETTING_FIELDS keys and defaults equal the Python DEFAULTS", ...)`: obtain Python's defaults with `JSON.parse(execFileSync("uv", ["run", "python", "-c", "import json;from gtm.settings_store import DEFAULTS;print(json.dumps(DEFAULTS))"], { cwd: "..", encoding: "utf8" }))` and assert same key set and, for each key, `def` equal to the Python value. This deletes the "keep two lists identical by eye" duplication for good.
  - `check("validSetting enforces ranges", ...)`: `walk_hour_utc` 24 and -1 false, 0 and 23 true; `walk_escalate_at` 1.5 false, 0.8 true; `walk_queries` `""` and `"  "` false, `"med spa"` true; `walk_schedule_enabled` `"yes"` false.
  - `check("enqueueJobOnce refuses a second identical open job", ...)`: call `enqueueJobOnce("walk", ["--tiles","1","TEST_once"])` twice, second must throw, exactly one queued row exists; then after the row is set `done` by the admin client a third call succeeds. Clean those rows (`payload->argv` contains `TEST_once`).
  - `check("retryTile only flips failed", ...)`: insert four coverage rows tagged `tile: "TEST_rt_<status>"` (metro `TEST`, state `ZZ`, statuses `failed, running, done, pending`) with the admin client; call `retryTile` on all four ids; only the failed row is `pending` with `error` null; the others keep their status. Delete `metro = 'TEST'` rows afterwards.
- [ ] **Step 2: Run** `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts`. Expected: FAIL (missing exports or key mismatch).
- [ ] **Step 3: Implement** the interfaces above. `SETTING_FIELDS` labels for the new keys: `Gemini Lite input USD per 1M tokens`, `Gemini Lite output USD per 1M tokens` (group API prices); `Run daily schedule` (bool; hint in the page, not here), `Schedule hour (UTC, 0-23)` (min 0 max 23), `Tiles per run` (min 1 max 20), `Search terms (comma separated, tried in order)` (text), `Max places per query` (min 1 max 200), `Go to next term when a query returned at least this share of the cap (0-1)` (float, min 0 max 1) in group `Scrape walk`; `Read blocked pages through a paid fallback` (bool) in `Page fetching`. Rewrite `app/settings/page.tsx` to use `useSettings` and `SettingInput`, rendering every group except `Scrape walk` (those live on the Scrape page; add one sentence with a link to `/scrape`). Add nav links `Scrape & Coverage` (`/scrape`) and `Batches` (`/batches`) to `app/layout.tsx` between Review and Outreach.
- [ ] **Step 4: Run** the verify command and `cd web && npm run typecheck`. Expected: `all ok`, no type errors.
- [ ] **Step 5: Settings page copy** (item 3). Replace the intro paragraph and add one muted line per group, exact text:
  - Page lead: `Values shown are what the worker uses right now; a key you have never saved shows its built-in default. Changes apply within a minute.` (the settings cache TTL is 60 seconds, `gtm/settings_store.py`.)
  - Gemini line (existing logic kept): `Paid Gemini is off|allowed: with it off, the model passes (signals, select, draft, replies) use Groq once the Google credit ends; owner research in enrich needs Gemini and stops and pauses its job. Replies are classified with Gemini Flash-Lite, priced by the two Lite settings.`
  - Group hints: Budget `Monthly budget and exchange rate used in the cost views.`; Google credit `Free-trial credit: it ends on the date below unless the full account is activated first.`; API prices `Third-party prices, unconfirmed; they only change what the cost views show.`; Daily caps `Each cap is in the provider's own unit and is checked before every paid call; 0 blocks the provider.`.
- [ ] **Step 6: Commit** `git add web/lib web/components web/app/layout.tsx web/app/settings/page.tsx web/scripts/verify.mts && git commit -m "feat: web settings list mirrors Python defaults, enqueueJobOnce, retryTile, nav links"`

### Task 2: `--named-only` retry flag (backend, TDD, parallel with 3 and 4)

**Files:**
- Modify: `gtm/enrich.py` (`run_enrich`), `gtm/cli.py` (`enrich` subparser and `cmd_enrich`)
- Test: `tests/test_enrich.py` (add one test next to the existing `retry_no_buyer` tests; read the file first and reuse its fake-db helper)

**Interfaces:**
- Produces: `run_enrich(db, finders, batch_id, limit=None, retry_no_buyer=False, named_only=False)`. When `retry_no_buyer` and `named_only` are both true the retry set is `cleaned` leads plus `no_buyer` leads that have a non-empty `owner_name`; unnamed `no_buyer` leads are not read and cost nothing. `named_only` without `retry_no_buyer` is a no-op. CLI: `enrich --batch B --retry-no-buyer --named-only`.

- [ ] **Step 1: Failing test** `test_retry_named_only_skips_unnamed_no_buyer`: batch with three `no_buyer` leads (one with `owner_name`/`owner_title`/no email, one with a name and a saved email, one with no name) and one `cleaned` lead; a counting finder returns `[]`. With `retry_no_buyer=True, named_only=True` the finder is called for the two named leads and the cleaned lead, never for the unnamed one; with `named_only=False` it is called for all four; the saved email of the second lead is still in the row afterwards.
- [ ] **Step 2: Run** `uv run pytest tests/test_enrich.py -k named_only -q`. Expected: FAIL (unexpected keyword).
- [ ] **Step 3: Implement.** In `run_enrich`, after building `q`, when `retry_no_buyer and named_only` filter unnamed no-buyers out of the result rows (`r["status"]` needs adding to the select list) rather than building an OR filter; one comprehension is enough. Add `--named-only` (`store_true`, help: `with --retry-no-buyer: only leads whose owner name is already known (spends credits only on them)`) and pass it through.
- [ ] **Step 4: Run** `uv run pytest tests/test_enrich.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/enrich.py gtm/cli.py tests/test_enrich.py && git commit -m "feat: enrich --named-only limits a retry to leads whose owner is already named"`

### Task 3: Migration 0012, spend per batch of 100 (parallel with 2 and 4)

**Files:**
- Create: `supabase/migrations/0012_batch_no_spend.sql`

**Interfaces:**
- Produces: view `batch_no_spend` (`security_invoker = true`, same pattern and comment as `0006_batch_metrics_view.sql`) with columns `batch_no int, apify_usd numeric, hunter_credits numeric, prospeo_credits numeric, serper_queries numeric, gemini_usd numeric`, each the sum of `cost_log` rows whose `lead_id` belongs to a lead with that `batch_no` (join `cost_log.lead_id = leads.id`, `leads.batch_no is not null`, grouped by `batch_no`, `filter (where provider = ...)`). Spend not attributed to a lead (scrape-time Apify, which is recorded against the scrape run only) is deliberately not in this view; the Batches page shows scrape spend per scrape run from the existing `batch_metrics` view and says so.

- [ ] **Step 1: Write the migration**, additive only. Owner approves before it is applied (same gate as 0010); apply with Supabase MCP `apply_migration` to project `alvxsbnfthvaiquhytig`.
- [ ] **Step 2: Failing check** is in Task 5 Step 1 (the view is read through `loadBatches`); here verify by SQL: `select * from batch_no_spend` returns without error and, for a seeded `TEST` lead with `batch_no = 9999` plus a `cost_log` row for that lead (`provider hunter, units 2`), returns `hunter_credits = 2` for 9999. Delete the test rows.
- [ ] **Step 3: Commit** `git add supabase/migrations/0012_batch_no_spend.sql && git commit -m "feat: batch_no_spend view, spend per batch of 100"`

### Task 4: Scrape & Coverage page (needs Task 1; parallel with 2 and 3)

**Files:**
- Create: `web/app/scrape/page.tsx`, `web/lib/coverage.ts`, `web/scripts/verify_scrape.mts`
- Modify: `web/app/globals.css` (one `.bar-fill` rule: a div with `width: N%` background accent, height 8px)

**Interfaces:**
- Consumes: `useRequireSession`, `useSettings`, `SettingInput`, `SETTING_FIELDS` (group `Scrape walk`), `enqueueJobOnce`, `retryTile`, `fetchAll`, `Coverage`, `SpendRow`, `Job`.
- Produces in `lib/coverage.ts`:
  - `loadCoverage(): Promise<Coverage[]>`: `fetchAll` over `coverage` ordered by `seq`.
  - `MetroRow = { metro_rank: number; metro: string; state: string; total: number; pending: number; running: number; done: number; failed: number; places: number; newLeads: number; saturated: number; lastScraped: string | null }` and `summarizeMetros(rows: Coverage[]): MetroRow[]` (pure, ordered by `metro_rank`, `lastScraped` = max `scraped_at`).
  - `walkJobOpen(jobs: Job[]): boolean`: true if any `walk` job is `queued`, `running` or `paused_budget`.
  - `runTilesArgv(n: number): string[]` returns `["--tiles", String(n)]` and throws for a non-integer or outside 1-20.

**Page content, top to bottom (one file, plain tables):**
1. Header `Scrape & Coverage` and a muted sentence: `The daily schedule is OFF by owner decision. Only the owner turns it on (below). Nothing here scrapes by itself: a button queues a job and the worker on the VM runs it.` The schedule checkbox is the `walk_schedule_enabled` input with a `pill` showing `schedule off`/`schedule on`.
2. Totals card: tiles done / total, a `.bar-fill` progress bar (guard total 0), counts per status, places found, new leads, saturated count, metros finished (all tiles done) / metros total.
3. Apify spend card: `$today` and `$month` from `spend_summary` (`provider = 'apify'`) against `cap_apify_usd_day`; `blocked` pill when the cap is 0, `at cap` pill when today >= cap (same logic as the Settings meter). Worst-case line from the tuning spike: `Typical tile $0.10 to $0.20, worst case $0.40 (docs/spikes/tile_tuning.md).`
4. Run card: number input (default = `walk_tiles_per_run`, min 1 max 20) and a primary button `Run N tiles now`. Under it: `Spends Apify money (about $0.20 per tile, at most $0.40) and is capped by the daily Apify cap.` Disabled while `walkJobOpen(jobs)` (shows `a walk job is already queued or running`), and shows an inline warning instead when the cap blocks. Click calls `enqueueJobOnce("walk", runTilesArgv(n))` then reloads. Below it the last 5 `walk` jobs (status, argv, error) reading the `jobs` table.
5. Walk settings: the `Scrape walk` group via `SettingInput` (`walk_schedule_enabled`, `walk_hour_utc`, `walk_tiles_per_run`, `walk_queries`, `walk_max_places`, `walk_escalate_at`), each with the existing save path.
6. Failed tiles table (only if any): metro, state, tile, error, button `Retry` (calls `retryTile`; the worker picks it up on the next walk; a note says so).
7. Metros table from `summarizeMetros`: rank, metro, state, done/total, running, failed, places, new leads, saturated, last scraped. Clicking a row (same `tr.row` pattern as the Leads page) expands that metro's tiles: tile, status pill, places found, new leads, saturated, queries run, scraped at, error. A search box filters metros by name or state. Statuses only; no pagination needed (201 metros).

- [ ] **Step 1: Write `scripts/verify_scrape.mts`** (same header, admin client, operator session mint and `check` helpers as `verify.mts`; import `loadCoverage`, `summarizeMetros`, `runTilesArgv`, `walkJobOpen` from `../lib/coverage`). Failing checks:
  - `loadCoverage` returns every row: its length equals `(await admin.from("coverage").select("id", { count: "exact", head: true })).count` (this is the more-than-1000-rows case: 1285 are seeded).
  - `summarizeMetros` on a fixed in-memory array: counts per status, `places` sum treating `null` as 0, `lastScraped` max, order by `metro_rank`, a metro with all tiles done has `done === total`.
  - `summarizeMetros` totals over the real rows equal the database: `sum(total)` equals the row count, and per-status sums equal `count: exact` queries with `.eq("status", s)` for the four statuses.
  - `runTilesArgv(3)` equals `["--tiles","3"]`; throws for `0`, `21`, `1.5`, `NaN`.
  - `walkJobOpen`: true for a queued walk, a running walk and a paused_budget walk; false for done, failed, cancelled and for a queued non-walk job.
  - Spend: the `spend_summary` row for apify, read under the operator session, has numeric `usd_today` and `usd_month` (the page's only spend query).
  - Run button path under RLS: `enqueueJobOnce("walk", runTilesArgv(1))` with a `TEST` marker is not possible for the real kind, so insert via `enqueueJob("walk_test", ["--tiles", "1"])`-style marker rows? Do not: a live worker would run a `walk` job. Use kind `walk_test` (the worker's `ALLOWED` set refuses unknown kinds, and `claim` skips test-marked jobs per migration 0011), assert one queued row, delete it. Never enqueue a real `walk` from a script.
- [ ] **Step 2: Run** `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_scrape.mts`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lib/coverage.ts`, then `app/scrape/page.tsx` as above, copying the structure of `app/settings/page.tsx` (`load` with `Promise.all`, one `err` state, `act()` wrapper). The page imports the same lib functions the script checks.
- [ ] **Step 4: Run** the script (Expected: `all ok`), `cd web && npm run typecheck` and `npm run build` (Expected: both succeed, `/scrape` is in the route list).
- [ ] **Step 5: Manual checklist** (`cd web && npm run dev`, sign in with the email link; the owner or the coordinator does this once): the page loads with the schedule pill `schedule off`; totals match `select status, count(*) from coverage group by status`; the progress bar width is done/total; expanding Manhattan shows 1 done tile that was saturated with 80 places and 71 new leads (the first live tile, HANDOFF section 0); the Run box rejects 0 and 21 (button disabled or error text); clicking `Run 1 tile now` creates exactly one queued `walk` job in the Jobs panel of `/settings` and a second click shows the already-open message (cancel that job from Settings afterwards if the owner did not mean to run it: this click spends Apify money once the worker claims it, so the checklist step is done only with the owner's yes); changing `walk_tiles_per_run` to 4 and back saves; inserting a `failed` tile row by hand shows it under Failed tiles and `Retry` turns it `pending`.
- [ ] **Step 6: Commit** `git add web/app/scrape web/lib/coverage.ts web/scripts/verify_scrape.mts web/app/globals.css && git commit -m "feat: Scrape & Coverage page"`

### Task 5: Batches page and retry-later button (needs Tasks 1, 2, 3)

**Files:**
- Create: `web/app/batches/page.tsx`, `web/lib/batches.ts`, `web/scripts/verify_batches.mts`

**Interfaces:**
- Consumes: `useRequireSession`, `useSettings`, `enqueueJobOnce`, `fetchAll`, `BatchMetrics`, `SpendRow`, `Job`, `STATUSES`; view `batch_no_spend` (Task 3); `enrich --named-only` (Task 2).
- Produces in `lib/batches.ts`:
  - `BatchNoRow = { batch_no: number; leads: number; byStatus: Record<string, number>; apify_usd: number; hunter_credits: number; prospeo_credits: number; serper_queries: number; gemini_usd: number }`; `loadBatchNos(): Promise<BatchNoRow[]>` reads `leads` (`batch_no, status` where `batch_no` not null, via `fetchAll`, ordered by `batch_no` then `id`) and `batch_no_spend`, and merges them, newest batch first.
  - `BATCH_SIZE = 100`; `fillLabel(r: BatchNoRow): string` returns `"37 of 100"`; a batch with `leads < 100` is "open" (only the highest batch number can be).
  - `RetryRow = { batch_id: string; name: string; created_at: string; named: number; unnamed: number }`; `loadRetryCandidates(): Promise<RetryRow[]>` counts, per scrape run, leads with `status = 'no_buyer'` split into `named` (`owner_name` not null and not empty) and `unnamed`, joined to the `batches` name; only runs with at least one `no_buyer` are returned.
  - `retryArgv(batchId: string): string[]` returns `["--batch", batchId, "--retry-no-buyer", "--named-only"]`.
  - `retryOpen(jobs: Job[], batchId: string): boolean`: an `enrich` job with the same argv in `queued, running, paused_budget`.
  - `creditState(spend: SpendRow[], vals: Record<string, unknown>): { provider: "hunter"|"prospeo"; today: number; cap: number; month: number; blocked: boolean }[]` using `cap_hunter_credits_day` and `cap_prospeo_credits_day`, units columns of `spend_summary`; `blocked` when cap is 0 or today >= cap.

**Page content:**
1. `Batches` header, muted explanation: `A batch is 100 verified, selected owners (numbered when a lead becomes selected, never renumbered). Leads that are scraped but not yet selected belong to a scrape run, listed below.`
2. Batches of 100 table: batch number, `fillLabel` (with an `open` pill on the unfilled newest one), then one column per funnel status from `STATUSES` that is non-zero anywhere (so the table stays narrow), then spend columns (Apify, Hunter credits, Prospeo credits, Serper, Gemini). Footnote: `Spend here is what was recorded against these leads (enrich, signals, drafts). Scrape-time Apify cost is per scrape run, below.` Empty state: `No batch numbers yet: leads get one when select picks them.`
3. Scrape runs table from `batch_metrics` (name, created, scraped, cleaned, enriched, Apify $, Hunter credits), newest first, with a column `Owner known, email not verified` showing `named` (and a muted `unnamed` count: `no owner found, parked`).
4. Retry later card (below the runs table, same card): credit state from `creditState` (Hunter and Prospeo credits used today / day cap / month, `blocked` pill), the text `Retry later re-runs the finders for leads whose owner name is known but whose email could not be verified. It spends Hunter and Prospeo credits (Hunter verification 0.5 credit each; see docs/spikes/owner_routes.md) and stops by itself when a provider runs out or hits its daily cap. A saved email is never erased. Nothing runs until you click.`, and per scrape run with `named > 0` a button `Retry later (N leads)`. Clicking opens `window.confirm("This spends Hunter and Prospeo credits on N leads. Continue?")`, then `enqueueJobOnce("enrich", retryArgv(batch_id))` and a reload. Disabled with the reason when `named === 0`, when `retryOpen(jobs, batch_id)` (`already queued or running`), or when both providers are `blocked`. Show the last 5 `enrich` jobs below with status and error (a retry that stops on credits shows its result counts in the Jobs panel of `/settings`).

- [ ] **Step 1: Write `scripts/verify_batches.mts`** (same harness). Seed with the admin client: a `TEST` batch row, `TEST_b%` leads with `batch_no` 9998 (3 leads: `selected`, `selected`, `sent`) and 9999 (1 lead), `no_buyer` leads on that batch (one named with `owner_name` and `owner_title`, one unnamed), and `cost_log` rows for a 9998 lead (`hunter` 2 units, `apify` `usd 0.01`). Failing checks:
  - `loadBatchNos` returns rows for 9998 and 9999 with `leads` 3 and 1, `byStatus` `{selected:2, sent:1}`, `hunter_credits` 2, `apify_usd` 0.01, ordered newest first; `fillLabel` gives `"3 of 100"`.
  - Totals check on the real data: `sum(leads)` over `loadBatchNos` equals `count: exact` of `leads where batch_no is not null` (covers more than 1000 leads when it gets there).
  - `loadRetryCandidates` for the test batch returns `named: 1, unnamed: 1`; a batch with no `no_buyer` leads is absent.
  - `retryArgv("abc")` equals `["--batch","abc","--retry-no-buyer","--named-only"]`; `retryOpen` true for queued, running and paused_budget `enrich` jobs with identical argv and false for another batch's argv, a `done` job, or a `clean` job.
  - `creditState` on fixed inputs: cap 0 gives `blocked`, today equal to cap gives `blocked`, below cap not blocked; month passes through.
  - Under the operator session, `enqueueJobOnce("enrich_test", retryArgv(testBatchId))` twice: first inserts one queued row, second throws. (Kind `enrich_test`, never the real `enrich`, so the VM worker cannot spend credits during verification.) Clean all `TEST` rows, jobs with the test argv and the cost rows.
- [ ] **Step 2: Run** `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_batches.mts`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lib/batches.ts` and `app/batches/page.tsx`, same page pattern as Task 4. Counting named versus unnamed is done in TypeScript over a `fetchAll` of `no_buyer` leads (`batch_id, owner_name`), not in SQL.
- [ ] **Step 4: Run** the script (Expected: `all ok`), `npm run typecheck`, `npm run build` (Expected: `/batches` in the route list).
- [ ] **Step 5: Manual checklist:** the Batches table shows batch numbers with `n of 100`, the newest marked `open`, and statuses summing to the batch count; the numbers of the Houston batch (8 selected, awaiting approval, HANDOFF section 0b) match `/review`; the Scrape runs table agrees with `/dashboard` for the same runs; the Retry card shows Hunter and Prospeo today/cap; Miliv-style cases: the Houston batch should show `named` equal to the leads Jamie Marcelle and Isam Balat are in (2 named `no_buyer`, per HANDOFF 0b, **unverified**: confirm with a query before trusting the number); the button is disabled for a run with `named = 0`; clicking it shows the confirm text naming credits; **do not confirm** in the checklist unless the owner says yes: confirming enqueues a real paid `enrich` job; after the owner's yes, exactly one queued `enrich ... --retry-no-buyer --named-only` job appears in Settings, and a second click is refused.
- [ ] **Step 6: Commit** `git add web/app/batches web/lib/batches.ts web/scripts/verify_batches.mts && git commit -m "feat: Batches page and retry-later button"`

### Task 6: Docs and full check (last)

**Files:**
- Modify: `docs/HANDOFF.md` (section 0 status table row for Plan 3b), `CLAUDE.md` (the verify command line: name the three scripts), `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (Plan 3 row: 3b built)

- [ ] **Step 1: Run everything:** `uv run pytest -q` (hits the real project, one process, `mkdir /tmp/gtm-pytest.lock` first; Expected: all pass, the previous count was 589 plus one new test), then the three verify scripts, `npm run typecheck`, `npm run build`. Expected: all green.
- [ ] **Step 2:** Edit the three docs: Plan 3b row `BUILT <date>` with the two pages, `--named-only`, migration 0012; CLAUDE.md verify line lists `verify.mts`, `verify_scrape.mts`, `verify_batches.mts`; roadmap row marked.
- [ ] **Step 3: Commit** `git add docs/HANDOFF.md CLAUDE.md docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md && git commit -m "docs: Plan 3b built"`

## Self-review notes

- Spec coverage: sections 2.4/2.5 (coverage, walk, Run now) Task 4; section 5 pages Tasks 4-5; section 11 retry later and waste buckets Tasks 2 and 5 (named retried, unnamed parked and shown as such); 15.9 batches of 100 Tasks 3 and 5; settings-page copy and the duplicated defaults Task 1. Out of scope and left alone: drafts, send, sheet import, metrics, home, replies, a monthly retry schedule, per-tile sub-tiling for saturated tiles (flagged only, per the tuning spike).
- Names checked across tasks: `enqueueJobOnce`, `retryTile`, `useSettings`, `SettingInput`, `loadCoverage`, `summarizeMetros`, `walkJobOpen`, `runTilesArgv`, `loadBatchNos`, `loadRetryCandidates`, `retryArgv`, `retryOpen`, `creditState`, `batch_no_spend` are defined once and used with the same signatures.
- Verification honesty: UI components have no automated test; what is automated is every query and every write the pages make (verify scripts under RLS, with `*_test` job kinds so the live VM worker cannot run a paid job), and what is manual is rendering, in the checklists. The existing `verify.mts` key-count assertion (`=== 16`) is already stale against the 25 Python defaults; Task 1 fixes it by comparing against Python itself.
