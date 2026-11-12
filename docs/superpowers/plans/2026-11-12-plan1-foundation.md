# GTM OS Foundation Implementation Plan (Plan 1 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the OS a settings store, complete spend tracking with budget caps and a paid-Gemini gate, and a job queue with a worker, plus a Settings page to steer them.

**Architecture:** Settings and jobs live in Supabase (new tables, operator-only RLS). A contextvar attaches batch and lead to every `cost_log` row. A `budget` module is called before each paid call and raises `BudgetExceeded`; Gemini falls back to Groq when not allowed. The worker claims jobs atomically (Postgres function) and runs the existing CLI passes by parsing the job's argv with the real argument parser, so there is one wiring of each pass.

**Tech Stack:** Python 3.12+ (uv, pytest, supabase-py, httpx), Supabase Postgres, Next.js 16 / React 19 / supabase-js (browser only, no new dependencies).

**Spec:** `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` (sections 6, 12, 15.5, 16). Roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`.

## Global Constraints
- Supabase Postgres is the only database; only `gtm/config.py` reads the environment (settings in the database are not environment).
- Every paid call writes a `cost_log` row with its batch and lead when known. Never print or commit keys. The Supabase secret key is script-side only, never in the browser.
- RLS: every table restricted to the operator (`auth.jwt() ->> 'email' = 'soban@kodoai.xyz'`); new tables get the same `operator_only` policy.
- No paid Gemini spend without the owner's confirmation: when the credit ends or runs out, Gemini calls fall back to Groq unless "Allow paid Gemini" is on, and then only up to its monthly cap. Default off.
- Credit facts: $298 of $300 left on 2026-11-12, ends 2027-02-09. Monthly budget 25,000 PKR at 276 PKR per USD; weekly target 200; both are settings.
- Send is always a separate explicit action (not touched by this plan). Footer values stay empty.
- Tests marked `db` hit the real Supabase project; one pytest process at a time; each test deletes only its own rows.
- Migrations are applied by hand through the Supabase MCP (`mcp__plugin_supabase_supabase__apply_migration`, project `alvxsbnfthvaiquhytig`); the `.sql` file is the record. Destructive SQL confirmations expire after 2 minutes.

## Review Focus
1. Two workers claim the same job: exactly one gets it (Task 5).
2. A worker dies mid-job: the job is not stuck in `running` forever (Task 5).
3. A cap is hit in the middle of an enrich run: unprocessed leads stay `cleaned` (not `no_buyer`) and the job ends `paused_budget`, not `failed` (Tasks 4, 5).
4. The credit end date passes with paid Gemini off: Vertex is never called and Groq answers (Task 4).
5. A wrong-typed or unknown setting (typed into the UI, or a cap of 0): the reader falls back to the default, the writer rejects it, and a cap of 0 blocks all spend for that API (Tasks 1, 3).

---

### Task 1: Settings table and store

**Files:**
- Create: `supabase/migrations/0007_jobs_settings.sql` (this task writes the whole migration: `settings`, `jobs`, `claim_job()`, `spend_summary` view, RLS)
- Create: `gtm/settings_store.py`
- Test: `tests/test_settings_store.py`

**Interfaces:**
- Produces:
  - `DEFAULTS: dict[str, bool | int | float | str]` with exactly these keys and defaults: `monthly_budget_pkr` 25000, `pkr_per_usd` 276, `weekly_target` 200, `allow_paid_gemini` False, `paid_gemini_monthly_cap_usd` 0, `credit_end_date` "2027-02-09", `credit_balance_usd` 298, `credit_balance_as_of` "2026-11-12", `gemini_input_usd_per_m` 1.5, `gemini_output_usd_per_m` 9.0 (third-party prices, unconfirmed), and daily caps `cap_apify_usd_day` 2.0, `cap_serper_queries_day` 700, `cap_gemini_usd_day` 5.0, `cap_hunter_credits_day` 100, `cap_prospeo_credits_day` 20, `cap_harvest_usd_day` 0.5 (proposed defaults, owner adjusts).
  - `setting(key: str, db=None) -> Any`: the stored value if present and of the default's type (int accepted for float keys; bool only for bool keys), else the default; cached 60 s per key.
  - `set_setting(db, key: str, value: Any) -> None`: upsert; `ValueError` on unknown key or wrong type; clears the cache.
  - `all_settings(db) -> dict[str, Any]`, `clear_cache() -> None`.
- Migration `0007` objects (used by later tasks): table `settings(key text primary key, value jsonb not null, updated_at timestamptz not null default now())`; table `jobs(id uuid pk default gen_random_uuid(), kind text not null, payload jsonb not null default '{}', status text not null default 'queued' check (status in ('queued','running','done','failed','cancelled','paused_budget')), run_after timestamptz not null default now(), started_at timestamptz, finished_at timestamptz, attempts int not null default 0, result jsonb, error text, created_at timestamptz not null default now())` with index on `(status, run_after)`; function `claim_job() returns jobs` that atomically sets one due `queued` job to `running` (`for update skip locked`), increments `attempts`, sets `started_at`, and returns it (execute revoked from `anon, authenticated`); view `spend_summary` (`security_invoker = true`) with one row per provider: `units_today, usd_today, units_month, usd_month` from `cost_log` (UTC day and month); RLS enabled with the `operator_only` policy on `settings` and `jobs`.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings_store.py` (db marker; a fixture saves and restores the `monthly_budget_pkr` row):
```python
def test_default_when_missing(): assert setting("weekly_target") == 200
def test_set_then_read_sees_new_value_immediately(): set_setting(db, "monthly_budget_pkr", 30000); assert setting("monthly_budget_pkr") == 30000
def test_unknown_key_rejected(): pytest.raises(ValueError, set_setting, db, "nope", 1)
def test_wrong_type_rejected(): pytest.raises(ValueError, set_setting, db, "weekly_target", "lots")
def test_bool_not_accepted_for_int(): pytest.raises(ValueError, set_setting, db, "weekly_target", True)
def test_bad_stored_value_falls_back_to_default(): db.table("settings").upsert({"key": "weekly_target", "value": "x"}).execute(); clear_cache(); assert setting("weekly_target") == 200
```
- [ ] **Step 2: Run** `uv run pytest tests/test_settings_store.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Write the migration, apply it through the Supabase MCP, and verify** with `select count(*) from settings` and `select claim_job()` (returns null on an empty queue). Then implement `gtm/settings_store.py` (module-level cache dict with timestamps; `setting` calls `get_db()` only on a cache miss when `db` is None).
- [ ] **Step 4: Run** `uv run pytest tests/test_settings_store.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add supabase/migrations/0007_jobs_settings.sql gtm/settings_store.py tests/test_settings_store.py && git commit -m "feat: settings store, jobs table, claim_job, spend_summary view"`

### Task 2: Spend attribution

**Files:**
- Modify: `gtm/costs.py` (`log_cost`), `gtm/enrich.py` (`run_enrich` per-lead loop), `gtm/signals.py` (`run_signals`), `gtm/select.py` (`run_select`), `gtm/draft.py` (`run_draft`, `run_followups`)
- Test: `tests/test_costs.py` (add), `tests/test_enrich.py` (add)

**Interfaces:**
- Produces: `spend_context(batch_id: str | None = None, lead_id: str | None = None)` context manager in `gtm/costs.py`; `log_cost` keeps its signature but uses the context values when `batch_id` or `lead_id` is None (explicit arguments win; nested contexts merge; the context resets on exit, including on exception).

- [ ] **Step 1: Write the failing tests.** Non-db tests monkeypatch `gtm.costs.get_db` to a fake whose `table("cost_log").insert(row).execute()` appends `row` to a list:
```python
def test_log_cost_inherits_batch_and_lead_from_context(): with spend_context(batch_id="b1", lead_id="l1"): log_cost("serper", 1, None); assert rows[-1]["batch_id"] == "b1" and rows[-1]["lead_id"] == "l1"
def test_explicit_args_win(): with spend_context(batch_id="b1"): log_cost("x", 1, None, batch_id="b2"); assert rows[-1]["batch_id"] == "b2"
def test_nested_contexts_merge_and_reset(): with spend_context(batch_id="b1"): with spend_context(lead_id="l1"): ...; log_cost("x",1,None); assert rows[-1]["lead_id"] is None
def test_context_resets_after_exception(): ...
```
and in `tests/test_enrich.py` (db): a finder that calls `log_cost("serper", 1, None, note="pytest-attrib")` inside `run_enrich`; assert the resulting `cost_log` row has `lead_id` equal to the lead's id and `batch_id` equal to the batch (delete rows by that note in cleanup).
- [ ] **Step 2: Run** both files. Expected: FAIL.
- [ ] **Step 3: Implement** `spend_context` with a `ContextVar[dict]`; wrap the body of each per-lead loop in `run_enrich`, `run_signals`, `run_select`, `run_draft` (and the per-lead loop of `run_followups`) in `with spend_context(batch_id=batch_id, lead_id=<lead id>)` (`run_followups` has no batch id: lead only).
- [ ] **Step 4: Run** `uv run pytest tests/test_costs.py tests/test_enrich.py tests/test_signals.py tests/test_select.py tests/test_draft.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: attach batch and lead to every cost_log row"`

### Task 3: Budget module

**Files:**
- Create: `gtm/budget.py`
- Test: `tests/test_budget.py` (no database: tests monkeypatch `gtm.budget._cost_rows` and `gtm.budget.setting`)

**Interfaces:**
- Consumes: `setting(key)` from Task 1.
- Produces:
  - `class BudgetExceeded(RuntimeError)`.
  - `CAP_KEYS: dict[str, str]` mapping `apify→cap_apify_usd_day, serper→cap_serper_queries_day, gemini→cap_gemini_usd_day, hunter→cap_hunter_credits_day, prospeo→cap_prospeo_credits_day, harvest→cap_harvest_usd_day`.
  - `_cost_rows(db, provider: str, since: datetime) -> list[dict]` (rows `{units, usd, created_at}` from `cost_log`; the single place budget reads spend).
  - `spent_since(db, provider: str, since: datetime) -> float`: sum of `usd` for apify, gemini, harvest; sum of `units` for serper, hunter, prospeo.
  - `credit_remaining_usd(db=None, now: datetime | None = None) -> float`: `credit_balance_usd` minus Gemini `usd` spent since `credit_balance_as_of`.
  - `gemini_allowed(db=None, today: date | None = None) -> bool`: True while `today <= credit_end_date` and `credit_remaining_usd() > 0`; otherwise True only if `allow_paid_gemini` and this month's Gemini usd is under `paid_gemini_monthly_cap_usd`.
  - `require(provider: str, amount: float = 1.0, db=None, now: datetime | None = None) -> None`: raises `BudgetExceeded` if today's (UTC) spend plus `amount` exceeds the provider's cap; for `gemini` also raises when `gemini_allowed()` is False. Unknown providers (groq) pass.

- [ ] **Step 1: Write the failing tests:**
```python
def test_require_passes_under_cap(); def test_require_raises_over_cap()   # serper 699 spent + 1 vs cap 700 passes; +2 raises
def test_cap_zero_blocks_all_spend()                                     # cap_hunter_credits_day = 0 -> require("hunter", 1) raises
def test_gemini_allowed_within_credit()
def test_gemini_blocked_after_credit_end_when_paid_off()                 # today = 2027-02-10
def test_gemini_blocked_when_credit_exhausted()                          # remaining <= 0 before end date
def test_paid_gemini_allowed_after_end_only_under_monthly_cap()          # allow_paid_gemini True; month spend 1.0 vs cap 2.0 ok, 2.0 blocked
def test_gemini_daily_cap_applies_inside_credit_period()
def test_unknown_provider_passes()
```
- [ ] **Step 2: Run** `uv run pytest tests/test_budget.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `gtm/budget.py`** per the interfaces. Day and month boundaries are UTC (my call, matches `spend_summary`).
- [ ] **Step 4: Run** `uv run pytest tests/test_budget.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** `git add gtm/budget.py tests/test_budget.py && git commit -m "feat: budget caps and paid-Gemini gate"`

### Task 4: Guards at every paid call, and Gemini dollar cost

**Files:**
- Modify: `gtm/llm.py` (`_vertex`, new `log_gemini_usage`), `gtm/researcher.py` (`gemini_step`), `gtm/search.py` (`serper_search`), `gtm/hunter.py` (`HunterPool._call`), `gtm/prospeo.py` (`ProspeoClient.find`), `gtm/harvest.py` (`HarvestClient.profile`), `gtm/apify.py` (`run_places`), `gtm/enrich.py` (`run_enrich`)
- Test: `tests/test_llm.py`, `tests/test_search.py`, `tests/test_enrich.py` (add)

**Interfaces:**
- Consumes: `require`, `BudgetExceeded`, `gemini_allowed` (Task 3); `setting` (Task 1).
- Produces: `log_gemini_usage(meta: dict) -> None` in `gtm/llm.py`: reads `promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`, `totalTokenCount` from `usageMetadata`; usd = (prompt × `gemini_input_usd_per_m` + (candidates + thoughts) × `gemini_output_usd_per_m`) / 1,000,000; calls `log_cost("gemini", totalTokenCount, usd, note="tokens")`. Both `_vertex` and `gemini_step` call `require("gemini", 0)` before the request and `log_gemini_usage` after.

- [ ] **Step 1: Write the failing tests:**
```python
def test_log_gemini_usage_prices_input_and_output_separately()   # 1,000,000 prompt + 1,000,000 candidates, prices 1.5 / 9.0 -> usd == 10.5
def test_thinking_tokens_count_as_output()
def test_vertex_not_called_when_gemini_not_allowed()             # gemini_allowed -> False; httpx.post patched to fail if called; complete_json returns the Groq fake's answer
def test_serper_search_raises_budget_exceeded_before_any_request()
def test_run_enrich_budget_exceeded_leaves_leads_cleaned()       # db: finder raises BudgetExceeded; counts == {"out_of_credits": 3}; all rows still "cleaned"
```
- [ ] **Step 2: Run** `uv run pytest tests/test_llm.py tests/test_search.py tests/test_enrich.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Call `require(provider, amount)` as the first statement of each paid call (serper 1; hunter 1; prospeo 1; harvest 0.01; apify `max_usd`; gemini 0). `run_enrich` catches `(OutOfCredits, BudgetExceeded)` in its existing out-of-credits branch.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: PASS (existing tests unchanged apart from fakes that must tolerate `require`; patch `require` in those tests' fixtures only if they fail).
- [ ] **Step 5: Commit** `git commit -am "feat: budget guards on every paid call; Gemini dollar cost"`

### Task 5: Jobs, worker and CLI commands

**Files:**
- Create: `gtm/jobs.py`, `gtm/worker.py`
- Modify: `gtm/cli.py` (extract `build_parser()`; add `worker` and `enqueue` subcommands)
- Test: `tests/test_jobs.py`, `tests/test_worker.py`
- Docs: `docs/HANDOFF.md` (file map, section 5), `CLAUDE.md` (Commands)

**Interfaces:**
- Consumes: `claim_job()` and `jobs` (Task 1), `BudgetExceeded` (Task 3).
- Produces:
  - `gtm/jobs.py`: `enqueue(db, kind: str, payload: dict | None = None, run_after: datetime | None = None) -> str`; `claim(db) -> dict | None` (calls the `claim_job` RPC); `finish(db, job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None` (sets `finished_at`); `requeue_stale(db, older_than_minutes: int = 60) -> int` (running jobs older than that go back to `queued`).
  - `gtm/cli.py`: `build_parser() -> argparse.ArgumentParser`; `main(argv: list[str] | None = None) -> None`. `gtm enqueue <kind> -- <pass flags>` inserts a job whose payload is `{"argv": [flags...]}`; `gtm worker [--poll 15]` runs `worker.main`.
  - `gtm/worker.py`: `ALLOWED = {"scrape","clean","enrich","signals","select","draft","followups","replies"}` (send is not runnable by a job until Plan 4); `_run_pass(kind: str, argv: list[str]) -> str` (parses `[kind, *argv]` with `build_parser()`, runs `a.fn(a)` with stdout captured, returns the output); `run_one(db, run_pass=_run_pass) -> str | None` (job id handled, or None when the queue is empty); `main(poll_seconds: int = 15) -> None` (loop; calls `requeue_stale` once an hour; Ctrl-C exits cleanly). Mapping: success → `done` with `{"output": last 4,000 chars}`; `BudgetExceeded` → `paused_budget`; `SystemExit`, any other exception, or a kind outside `ALLOWED` → `failed` with `error`.
  - ponytail: job results are captured stdout text; structured results come when a page needs numbers.

- [ ] **Step 1: Write the failing tests** (db marker; every job created has `payload.test = 1` and is deleted in cleanup):
```python
def test_enqueue_then_claim_returns_the_job_running()
def test_claim_is_atomic_second_claim_gets_nothing()            # one queued job, two claims -> exactly one non-None
def test_future_run_after_is_not_claimed()
def test_requeue_stale_returns_old_running_job_to_queue()       # started_at 2 h ago -> requeued; one started now untouched
def test_run_one_success_marks_done_with_output()               # fake run_pass returns "ok"
def test_run_one_budget_exceeded_marks_paused_budget()
def test_run_one_exception_marks_failed_with_error()
def test_run_one_unknown_kind_fails_without_running_anything()
def test_run_one_empty_queue_returns_none()
def test_run_pass_parses_argv_with_the_real_parser()            # non-db: _run_pass("clean", []) raises SystemExit (argparse: --batch required)
```
- [ ] **Step 2: Run** `uv run pytest tests/test_jobs.py tests/test_worker.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `jobs.py`, `worker.py`, and the `cli.py` refactor (move the parser construction out of `main` unchanged; keep every existing flag and default).
- [ ] **Step 4: Run** `uv run pytest tests/test_jobs.py tests/test_worker.py -v` then `uv run python -m gtm.cli --help`. Expected: PASS; help lists `worker` and `enqueue`.
- [ ] **Step 5: Update docs** (file map rows for `settings_store`, `budget`, `jobs`, `worker`; the two new commands) and **commit** `git add gtm tests docs CLAUDE.md && git commit -m "feat: jobs table access, worker, enqueue and worker CLI commands"`

### Task 6: Settings page, spend meter, jobs panel

**Files:**
- Create: `web/app/settings/page.tsx`, `web/lib/settings.ts`
- Modify: `web/app/layout.tsx` (nav link), `web/lib/actions.ts`, `web/lib/types.ts`, `web/scripts/verify.mts`, `web/scripts/rls_intruder.mts`
- Docs: `docs/HANDOFF.md` (pages table)

**Interfaces:**
- Consumes: tables `settings`, `jobs` and view `spend_summary` (Task 1).
- Produces:
  - `web/lib/settings.ts`: `SETTING_FIELDS` listing every key from Task 1's `DEFAULTS` with `{ key, label, type: "int" | "float" | "bool" | "date", group }` (a mirror of the Python defaults; keep the key lists identical).
  - `web/lib/types.ts`: `Setting {key, value, updated_at}`, `Job {id, kind, payload, status, run_after, started_at, finished_at, attempts, result, error, created_at}`, `SpendRow {provider, units_today, usd_today, units_month, usd_month}`.
  - `web/lib/actions.ts`: `saveSetting(key: string, value: unknown): Promise<void>` (upsert into `settings`; throws if the key is not in `SETTING_FIELDS` or the value has the wrong type); `enqueueJob(kind: string, argv: string[]): Promise<void>`; `cancelJob(id: string)` (only while `queued`); `retryJob(id: string)` (only from `failed` or `paused_budget`).
  - Page `/settings`: groups Budget, Google credit (with the **Allow paid Gemini** switch, off by default, and its monthly cap), API prices, Daily caps; a spend meter (today and month-to-date per provider from `spend_summary` against the day caps); a jobs panel (last 50 jobs with status and error, Retry and Cancel buttons).

- [ ] **Step 1: Write the failing verification.** In `web/scripts/verify.mts`, with the operator session and `admin` reads, add checks: `saveSetting("weekly_target", 150)` persists; `saveSetting("nope", 1)` and `saveSetting("weekly_target", "x")` throw and leave the table unchanged; `enqueueJob("clean", ["--batch","TEST"])` inserts a `queued` job; `cancelJob` cancels it; `cancelJob` on a `running` job changes nothing; `retryJob` requeues a `failed` job and ignores a `done` one. Cleanup: restore `weekly_target`, delete test jobs (`payload->>'test'` or kind+argv marker). In `web/scripts/rls_intruder.mts`, add: the non-operator reads 0 rows from `settings`, `jobs` and `spend_summary` and cannot insert into `settings` or `jobs`.
- [ ] **Step 2: Run** `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts`. Expected: FAIL (actions missing).
- [ ] **Step 3: Implement** the types, actions (guarded updates by `.eq("status", ...)` like the existing actions), `SETTING_FIELDS`, the page (client component, `useRequireSession`, existing `globals.css` classes, no new dependencies) and the nav link.
- [ ] **Step 4: Run** `cd web && npm run typecheck`, then both verify scripts. Expected: typecheck clean; `all ok` from `verify.mts`; `rls_intruder.mts` passes.
- [ ] **Step 5: Run the app** `cd web && npm run dev`, open `/settings`, change the weekly target, toggle and untoggle **Allow paid Gemini**, enqueue a `clean` job and cancel it. Then **commit** `git add web docs && git commit -m "feat: Settings page with spend meter and jobs panel"`

---

## Self-review (done against the spec)
- Spec coverage: settings store and credit facts (16), budget caps and per-API daily limits (12, 15.5), no paid Gemini without confirmation (16), batch and lead on every paid call (10, 15.5), jobs and worker (6), Settings page (5). Not in this plan by design: Home credit warning and budget meter on Home (Plan 6), the VM (Plan 2), scheduling jobs (Plan 3), Send (Plan 4).
- Types match across tasks: `setting`, `set_setting`, `require`, `BudgetExceeded`, `gemini_allowed`, `log_gemini_usage`, `enqueue/claim/finish/requeue_stale`, `build_parser`, `run_one`, `_run_pass`.
- Open risk: the Gemini and Serper prices in the defaults are third-party figures; the owner edits them on the Settings page. The daily-cap defaults are my proposal.
