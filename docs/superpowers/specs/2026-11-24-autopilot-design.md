# Autopilot design: keep the current batch of 100 filling until the money runs out (2026-11-24)

## Intent and why
The owner works in batches of 100 outreach leads (Notion Batch01-03). Today nothing chains the passes: each (`clean`, `verify-sheet`, `enrich`, `signals`, `select`, `draft`) is run by hand on one scrape or import run. The owner wants the OS to run the whole pipeline by itself until the batch has 100, open the next batch, and stop only at the owner's decisions or when money runs out. To continue, the owner adds credit and presses Resume.

## Goals
- One switch, "Autopilot": while on, the OS scrapes, cleans, verifies, enriches, signals and selects until the current batch holds 100 leads, then keeps going into the next batch.
- An owner-set expense limit (USD) per run; a clear paused reason; Resume after adding credit.
- Batch numbering that matches Notion: Batch03 already holds 32 leads (30 sent, 2 bounced, checked 2026-11-24), so OS leads fill Batch03 from lead 33, then Batch04 opens at 100.

## Non-goals and anti-goals
- Never approves a lead, never sends, never turns `sending_on` on: approval on `/review` and Start sending stay the owner's. A lead the owner never approves is simply waiting.
- No Gemini auto-conversation, no metrics (Plan 6), no new scrape sources.
- Anti-goal: silent overspend, or looping on a failing step.

## Constraints
- Existing passes and their per-source-batch `--batch` flag stay unchanged; the worker already runs one job at a time from the `jobs` table; a deploy cancels a running job.
- Existing guards stay: per-provider daily caps (`cap_*_day`), `BudgetExceeded` mapped to job status `paused_budget`, paid-Gemini gate, import allowance. Autopilot adds a run limit on top; it never removes a cap.
- Hand-made rows use `REHEARSAL_`, tests `TEST_`; tests never touch real batches, real settings or the real mailbox.

## Approaches (owner picked A, 2026-11-24)
- **A. Controller tick on the worker, enqueueing the existing jobs one at a time (picked).** Like `queue_tick`: a small check each loop looks at lead states and queues the next step. State lives in the database, survives deploys and drops, no pass changes.
- B. One long autopilot job looping through passes: hours-long jobs are killed by deploys and network drops, hard to see from the UI. Dropped.
- C. Each pass schedules itself: nothing owns the "stop at 100" rule, so it over-scrapes. Dropped.

## The design
**Settings (new):** `autopilot_on` (bool, default off), `autopilot_limit_usd` (number), `autopilot_started_at` (timestamp, set on Start or Resume), `autopilot_state` (text: `running`, `waiting_approval`, `paused: <reason>`), `autopilot_target` (100), `batch_base` (JSON `{"3": 32}`: leads already in a batch outside the OS). All appear on the Settings page; no migration (settings is a key/value table).

**Controller (`autopilot_tick(db, now)` in `gtm/autopilot.py`, called from the worker loop with its own try block).** Does nothing when off, when any autopilot-kind job is queued or running, or when paused. Otherwise, in this priority:
1. *Limit:* sum `cost_log.usd` since `autopilot_started_at`; at or above `autopilot_limit_usd` set state `paused: spend limit` and stop. (Hunter/Serper/Prospeo credits have no USD; they are bounded by their daily caps only, a known ceiling.)
2. *Budget:* the last pipeline job ended `paused_budget`: if its provider cap is a daily cap, wait until the next UTC day and retry; if it is credit or a lifetime allowance, set `paused: <message>` until Resume. Three consecutive failed jobs set `paused: errors`.
3. *Advance leads:* for each source batch with leads waiting in a stage, queue the next pass for that batch in order: `scraped` clean; sheet leads with an email `verify-sheet --confirm`; `cleaned` enrich; `enriched` signals; `signalled` select (select numbers leads into batches via `assign_batches`). Approved `selected` leads without a draft get `draft --batch`.
4. *Need more leads:* only when nothing in 3 is queued: if (leads numbered into the current batch + leads in flight at cleaned, enriched, signalled) is under `autopilot_target`, queue `walk` with the setting `walk_tiles_per_run`; if none waiting and the walk finds no tiles, set `paused: no tiles left`.
5. *Done:* nothing to queue and unapproved `selected` leads exist: `waiting_approval`; else `running` (idle).

**Numbering.** `plan_numbers` counts `batch_base` as already used (Batch03 starts at 32, so the next OS lead is the 33rd). The 28 selected leads now numbered 1 are renumbered to 3 once (a database write the owner approves first).

**UI (small, on `/batches`):** autopilot card: state line, Start/Resume with a limit field (writes `autopilot_limit_usd` and `autopilot_started_at`, sets `autopilot_on`), Pause. Plan 8's batch cards come after.

## What is left to the builder
Exact stage-to-pass mapping details and per-batch counting queries, job payload shape, the in-flight margin (start at 1:1; yield is about 1 in 5, so the walk gate is deliberately a count of leads, not tiles), tests with fake jobs and `TEST` batches, copy for the paused reasons.

## Gates for the build
No VM deploy, no real walk or paid call, no renumbering of real leads, no turning autopilot on without the owner. Rehearse the controller against test rows with fake job runners; first real run is the owner's yes and a small limit (for example $2).

## Calls made after the builder check (mine unless marked; correct any)
- **Limit is soft (owner approved 2026-11-24):** checked between jobs; one job can overshoot. The per-provider daily caps (Apify $2/day by default) are the hard backstop, so the real worst case is one job, never more than a day's caps. Counts every `cost_log.usd` row since `autopilot_started_at`, manual jobs included (conservative). Resume's limit is a new total from that moment (the clock resets).
- **Approval means lead approval on `/review`** (`leads.approved`), separate from approving drafts. The controller queues `draft --batch` for any source batch holding approved selected leads without drafts, and again when more are approved. `waiting_approval` is the state when only unapproved selected leads remain.
- **Bound on waiting work:** scraping stops while 100 or more selected leads are unapproved (state `waiting_approval`); this bounds what piles up. `assign_batches` already rolls numbering over from one batch to the next, so a `select` that crosses 100 splits across Batch03 and Batch04 with no change.
- **Counts and renumbering:** 28 leads are `selected` today, all `batch_no` 1 (the handoff's 10 and 20 are stale). Renumbering 1 to 3 ships as a one-off CLI command with a dry run that the owner confirms; it runs before `batch_base` takes effect, so nothing clashes. `plan_numbers` treats `batch_base` as occupied slots, so the 28 become positions 33 to 60 of Batch03.
- **Walk and credit:** turning Autopilot on overrides the "walk stays off" setting on purpose (owner 2026-11-24). `BudgetExceeded` gets a `kind` field (`daily` or `credit`) so the controller can tell a daily cap (retry next UTC day) from credit or a lifetime allowance (pause until Resume). An Apify balance error that is not a `BudgetExceeded` fails the job; three failures in a row pause with "errors".
- **Sheet leads:** Autopilot never imports a sheet. It does pick up leads already imported. It queues `verify-sheet --confirm` for them (spends 0.5 Hunter credit per email inside the existing `import_hunter_allowance_credits`, which is finite). When that allowance is spent, verify is skipped and the leads go on to `enrich`.
- **No loops:** a pass runs at most once per source batch per run (a done job after `autopilot_started_at` counts as tried). Leads a pass leaves in the same stage are not retried until Resume. `no_buyer` leads are never retried by Autopilot.
