# Plan 6: Metrics, Home and Replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Show the owner, after each batch of 100, the send, bounce, reply and booked rates and the cost per verified owner and per reply; add Home, a Replies page and history by day, week, month and quarter.

**Architecture:** One additive migration (two event timestamps stamped by triggers, one aggregate view `cost_daily`, three optional price settings) and pure TypeScript for everything else: `web/lib/metrics.ts` (cohorts, rates, attribution, periods, angles) and `web/lib/home.ts` plus `web/lib/replies.ts` (Home and Replies logic), each unit-tested without a database. Loaders sit in separate files per page. The worker and the Python passes do not change.

**Tech Stack:** Supabase Postgres (migration, triggers, a `security_invoker` view), Next.js 16 browser app, TypeScript, `tsx` scripts, pytest (db-marked).

**Spec:** `docs/superpowers/specs/2026-11-26-plan6-metrics-design.md` (read section 7.1 definitions and 7.3 attribution before Task 3).

## Global Constraints
- Docs-style rules: no emojis, no invented numbers. A credit with no price is shown as credits, never as dollars. Empty data prints `n/a`, never `0%` or `NaN`.
- Real leads only: `place_id` not starting `TEST_` or `REHEARSAL_` (`gtm/send.py is_test_lead`); runs not named `TEST...` or `REHEARSAL...`. Every loader takes `includeTest = false`; only `verify_metrics.mts` passes true.
- Pure logic imports no Supabase. Loaders read through `fetchAll` with a stable order. Writes stay in `web/lib/actions.ts` (`setOutcome`, `markBooked`); no new write action.
- Tests and verify scripts: `TEST_` place ids, batch names starting `TEST`, `batch_no` left null (a numbered TEST lead would move the live autopilot's current batch). Run one pytest or verify process at a time (`mkdir /tmp/gtm-pytest.lock`). Verify scripts and db tests only while `autopilot_on` is false, or with `ALLOW_LIVE_AUTOPILOT=1` set by the owner.
- Month and day boundaries on Metrics are UTC (as `spend_summary` and the caps); Home's "yesterday" is the browser's local calendar day.
- Do not commit unless the executor is told to; do not touch the untracked Codex files.

## Review Focus
- Nothing sent yet (the real state today): every rate cell and per-reply cost shows `n/a`; no page crashes on empty arrays. Tests: Task 3 `rate`, `cohort`, `batchRows` checks; Task 10 browser run on the real, empty data.
- A scrape run with spend and no verified owner: its spend appears in "not allocated" and the four buckets still add up to total spend. Tests: Task 3 `allocateSpend` checks.
- TEST_ and REHEARSAL_ rows (rehearsal sends to the owner's own Gmail) must not touch any number. Tests: Task 3 `cohort` and `dropTestRuns`, Task 9 `loadMetricsData drops TEST rows by default`.
- Outcomes stored before the migration have no `outcome_at`: they count in cohort rates, show as "undated" in history, and never create a 1970 or null bucket. Tests: Task 1 trigger tests, Task 3 `historyRows`.
- Batch03 holds 32 leads outside the OS (`batch_base`): fill counts them, rates never do, and the Notion Batch03 row is not summed with the OS row. Tests: Task 3 `batchRows` and `HISTORY` checks.

## Task groups (parallelisable)
Group A (parallel, disjoint files): Tasks 1, 2, 3. Then Task 4 (consumes Task 3's `Spend` and `Prices`). Then Group B in parallel (disjoint files): Tasks 5, 6, 7, 8. Then Group C: Tasks 9, 10, 11.

### Task 1: Migration 0016 and event-timestamp tests (Group A)
**Files:** Create `supabase/migrations/0016_metrics_events.sql`, `tests/test_metrics_events.py`.
**Interfaces:** Produces `touches.outcome_at timestamptz`, `leads.booked_at timestamptz`, view `cost_daily(day date, provider text, run_id uuid, units numeric, usd numeric)`.
- [ ] **Step 0 (read-only, selects only, nothing written):** from the real project count `cost_log` rows total and with both `batch_id` and `lead_id` null, `touches` with `outcome` not null, and `touches` with status `sent`. Put the four numbers in the handoff note (they size the "no batch or lead" and "undated" lines); commit nothing.
- [ ] **Step 1:** In `tests/test_metrics_events.py` write, all `@pytest.mark.db`, `TEST_mev` place ids, a `new_batch(db, "TEST metrics events", ...)` batch, cleanup in `finally`: `test_outcome_at_is_set_when_outcome_first_set` (insert a touch with `outcome="positive"`: `outcome_at` is not null; update a touch from null to `negative`: set), `test_outcome_at_is_not_overwritten_when_outcome_changes` (positive then negative: same `outcome_at`), `test_outcome_at_stays_null_without_an_outcome`, `test_booked_at_is_set_when_status_becomes_booked_and_kept` (replied to booked sets it; a later update leaves it), `test_cost_daily_groups_by_utc_day_provider_and_run` (two apify rows one run one day sum; a 23:30Z and a 00:30Z row land on two days), `test_cost_daily_attributes_a_lead_only_row_to_the_leads_run`, `test_cost_daily_keeps_a_row_with_no_batch_or_lead_as_null_run`, `test_cost_daily_is_empty_for_a_signed_out_visitor` (publishable key, expects `[]`, as `test_signed_out_visitors_see_nothing_through_the_view`).
- [ ] **Step 2:** Run `uv run pytest tests/test_metrics_events.py -q` under the lock. Expected: FAIL (`outcome_at` does not exist).
- [ ] **Step 3:** Write the migration. Triggers (before insert or update, `tg_op` aware): `touches.outcome_at := now()` when `outcome` is not null and `outcome_at` is null and (insert, or `old.outcome` is distinct from `new.outcome`); `leads.booked_at := now()` when `status = 'booked'` and `booked_at` is null. The view groups `cost_log` by `(created_at at time zone 'utc')::date`, `provider`, `coalesce(c.batch_id, l.batch_id)` (left join `leads l on l.id = c.lead_id`), `sum(units)`, `coalesce(sum(usd), 0)`, `with (security_invoker = true)`. No test-data filter in the view (the TypeScript drops it).
- [ ] **Step 4 (hard gate):** STOP. The owner applies the migration to the real project (the way earlier migrations were applied). Then rerun Step 2's command. Expected: all pass, TEST rows deleted.
- [ ] **Step 5:** Commit `feat: metrics event timestamps and cost_daily`.

### Task 2: Optional credit prices (Group A)
**Files:** Modify `gtm/settings_store.py` (DEFAULTS and `_ok`), `web/lib/settings.ts`, `tests/test_settings_store.py`.
**Interfaces:** Produces settings `price_hunter_usd_per_credit`, `price_prospeo_usd_per_credit`, `price_serper_usd_per_credit`: float, default `0.0` (0 = unpriced), group "API prices", `min: 0` on the web side. The Serper price covers `serper` and `serper_maps`; the Hunter price covers `hunter` and `hunter_import`.
- [ ] **Step 1:** Failing tests: `test_credit_price_defaults_are_zero_floats_meaning_unpriced`, `test_negative_credit_price_falls_back_to_default` (a stored `-1` reads as `0.0`; `set_setting` rejects it).
- [ ] **Step 2:** Run `uv run pytest tests/test_settings_store.py -q`. Expected: FAIL.
- [ ] **Step 3:** Add the three keys; in `_ok` add one rule for keys starting `price_` (number, not bool, `>= 0`). Mirror them in `SETTING_FIELDS` with labels "Hunter USD per credit", "Prospeo USD per credit", "Serper USD per credit". The "API prices" hint already says they only change the cost views.
- [ ] **Step 4:** Rerun Step 2 (PASS), then `cd web && npx tsx scripts/settings_groups.mts` (pass). The equality check of Python and web defaults is `scripts/verify.mts`: run it only when autopilot is paused.
- [ ] **Step 5:** Commit `feat: optional credit price settings`.

### Task 3: Pure metrics core (Group A)
**Files:** Create `web/lib/metrics.ts` (no Supabase import), `web/scripts/metrics_unit.mts` (plain `assert`, one labelled `check(name, cond)` per line, like `runnow_unit.mts`).
**Interfaces:** Produces
- Types: `Grain = "day"|"week"|"month"|"quarter"`; `LeadRow = {id; place_id; batch_id: string|null; batch_no: number|null; status; vector: string|null; signal_led: boolean; owner_name: string|null; owner_email: string|null; email_verified: boolean|null; reject_reason: string|null; created_at; booked_at: string|null}`; `TouchRow = {lead_id; touch_no: number; status; sent_at: string|null; outcome: string|null; outcome_at: string|null}`; `CostDay = {day: string; provider: string; run_id: string|null; units: number; usd: number}`; `RunRow = {id; name; created_at}`; `Prices = {hunter: number; prospeo: number; serper: number}`; `Spend = Record<string, {units: number; usd: number}>`; `Cohort = {sent; bounced; delivered; replied; positive; booked}` (numbers).
- Filters: `isTestLead(placeId: string): boolean`, `isTestRun(name: string): boolean`, `dropTestRuns(costs: CostDay[], runs: RunRow[]): CostDay[]` (keeps null-run rows), `isOwner(l): boolean`.
- Time: `periodStart(iso: string, grain: Grain): string` (UTC `YYYY-MM-DD`, week starts Monday), `periodRange(from: string, to: string, grain: Grain): string[]`, `previousRange(from: string, to: string): {from: string; to: string}`.
- Money: `spendFrom(rows: {provider: string; units: number; usd: number|null}[]): Spend`, `addSpend(a: Spend, b: Spend): Spend`, `pricedUsd(s: Spend, p: Prices): number`, `perUnit(s: Spend, n: number): Spend | null`, `rate(k: number, n: number): number | null`.
- Cohorts: `cohort(leads: LeadRow[], touches: TouchRow[]): Cohort`; `allocateSpend(costs: CostDay[], leads: LeadRow[]): Allocation` with `Allocation = {byBatchNo: Map<number, Spend>; notNumbered: Spend; noOwners: Spend; unattributed: Spend}`; `batchRows(leads, touches, alloc: Allocation, base: Record<number, number>): BatchRow[]` newest first, `BatchRow = Cohort & {batch_no; fill; base; owners; spend: Spend}`; `byAngle(leads, touches, batchNo?: number): AngleRow[]` (`{vector; lane: "signal-led"|"relevance-led"} & Cohort`); `whereLeadsDie(leads): {reason: string; n: number}[]`; `historyRows(a: {leads; touches; costs; grain; from; to}): HistoryRow[]` (`{start; scraped; owners; touch1; followups; bounces; replies; booked; spend}`); `undatedCounts(touches: TouchRow[], leads: LeadRow[]): {bounces: number; replies: number; booked: number}`; `HISTORY` (Notion rows Batch01-03: `{label; sent; bounced; negative; outOfOffice; positive}` copied from `docs/spikes/sending_history.md`, comment cites it).
- [ ] **Step 1:** Write `metrics_unit.mts` with these checks (fixtures small and in memory): `periodStart: week starts Monday`, `periodStart: 2026-12-31 is Q4 and 2027-01-01 is Q1`, `periodStart ignores the process time zone`, `periodRange lists empty buckets too`, `previousRange: same length, ends the day before from`, `rate: n of 0 is null, never NaN`, `cohort: nothing sent gives zeros`, `cohort counts only leads whose Touch 1 is sent`, `cohort: replied is status replied, unsubscribed, booked or outcome positive, negative, other, opt_out; a bounce outcome is not a reply`, `cohort: delivered is sent minus bounced`, `cohort excludes TEST_ and REHEARSAL_ leads`, `dropTestRuns drops TEST and REHEARSAL runs and keeps null-run rows`, `pricedUsd: unpriced credits add nothing, a price adds units times price, hunter_import uses the hunter price`, `perUnit: null when n is 0`, `allocateSpend: a run's spend splits equally over its verified owners`, `allocateSpend: a run with spend and no verified owner lands in noOwners`, `allocateSpend: a null-run row lands in unattributed`, `allocateSpend: owners not yet numbered land in notNumbered`, `allocateSpend conserves total spend over its four buckets`, `batchRows: base counts toward fill and not toward rates`, `batchRows: a base-only batch still gets a row`, `batchRows: a batch with no sends has null rates`, `byAngle: groups by vector and lane`, `byAngle: signal_led false is relevance-led`, `whereLeadsDie: sorted descending and splits no_buyer named from no owner found`, `historyRows: events land in their UTC bucket (sent_at, outcome_at, booked_at, created_at)`, `historyRows: an outcome without outcome_at is counted in undatedCounts, not bucketed`, `HISTORY sums to 218 sent, 12 bounced, 4 negative, 2 out of office, 0 positive`.
- [ ] **Step 2:** Run `cd web && npx tsx scripts/metrics_unit.mts`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement. Attribution is spec 7.3: group costs by `run_id`; a run's spend is split equally over its verified owners (leads with that `batch_id` and `isOwner`, test leads dropped first); each owner's share goes to `byBatchNo` when it has a `batch_no`, else `notNumbered`; a run with spend and zero owners goes to `noOwners`; `run_id` null goes to `unattributed`. `// ponytail: reads every lead and sent touch in the browser; fine to a few thousand leads, move cohorts into a view when a page load takes seconds.`
- [ ] **Step 4:** Rerun with `TZ=Asia/Karachi` and again with `TZ=America/Los_Angeles`. Expected: all ok both times.
- [ ] **Step 5:** Commit `feat: metrics pure logic`.

### Task 4: Pure Home and Replies logic (after Task 3)
**Files:** Create `web/lib/home.ts`, `web/lib/replies.ts`, `web/scripts/home_unit.mts`.
**Interfaces:** Consumes `Spend`, `Prices`, `pricedUsd` from `metrics.ts`. Produces
- `dayRange(now: Date, daysAgo: number): {from: string; to: string}` (ISO UTC bounds of that local calendar day).
- `creditStatus(v: {credit_end_date: string; credit_balance_usd: number; credit_balance_as_of: string}, geminiUsdSince: number, now: Date): {remaining: number; daysLeft: number; ended: boolean; warn: string | null}`: `remaining = balance - geminiUsdSince` (floor 0); ended when UTC today is on or after the end date or remaining is 0; warn when remaining is under 20 percent of `credit_balance_usd`, or `daysLeft` under 14, or ended (the `gtm/budget.py` rule and operating-layer 16).
- `budgetMeter(monthSpend: Spend, creditEnded: boolean, v: {monthly_budget_pkr: number; pkr_per_usd: number}, p: Prices): {spentUsd: number; budgetUsd: number; pct: number | null; creditsUnpriced: Record<string, number>}` (Gemini counts only when `creditEnded`).
- `HomeCounts = {replies: number; mailboxPaused: string | null; approvedWhileOff: number; followupsDrafted: number; draftsWaiting: number; selectedUnapproved: number; batch: {no: number; fill: number} | null}` and `nextAction(c: HomeCounts): {text: string; href: string}` in this order: replies (`/replies`), paused mailbox (`/send`), approved while sending off (`/send`), follow-ups (`/send`), drafts (`/drafts`), selected unapproved (`/review`), open batch (`/batches`), else "Nothing waiting".
- `replyBucket(status: string, outcome: string | null): "look"|"positive"|"booked"|"declined"|"bounced"|null` and `gmailThreadUrl(address: string, threadId: string): string` (`https://mail.google.com/mail/?authuser=<encoded address>#all/<threadId>`).
- [ ] **Step 1:** Checks in `home_unit.mts`: `dayRange: yesterday is the previous local calendar day`, `dayRange: 25 hours on the US fall-back day` (runs only when `TZ=America/Los_Angeles`, `now` 2026-11-02, `daysAgo` 1), `creditStatus: 298 left with 90 days is not a warning`, `creditStatus: warns under 20 percent`, `creditStatus: warns under 14 days`, `creditStatus: ended on the end date`, `budgetMeter: 25000 PKR at 276 is a budget of 90.58 USD`, `budgetMeter: Gemini counts only after the credit ended`, `budgetMeter: unpriced credits are listed, not guessed`, `budgetMeter: budget 0 gives null pct`, `nextAction: each state alone`, `nextAction: replies beat everything and each later rule beats the next`, `nextAction: nothing waiting`, `replyBucket: replied with no outcome or other needs a look`, `replyBucket: replied positive is positive`, `replyBucket: replied negative and unsubscribed are declined`, `replyBucket: booked beats a positive outcome`, `replyBucket: sent is null`, `gmailThreadUrl encodes the address`.
- [ ] **Step 2:** Run `cd web && npx tsx scripts/home_unit.mts`. Expected: FAIL.
- [ ] **Step 3:** Implement the five functions; no Supabase import.
- [ ] **Step 4:** Rerun under `TZ=Asia/Karachi` and `TZ=America/Los_Angeles`. Expected: all ok.
- [ ] **Step 5:** Commit `feat: home and replies pure logic`.

### Task 5: Metrics page (Group B)
**Files:** Move `web/app/dashboard/page.tsx` to `web/app/metrics/page.tsx` (`git mv`) and extend; Create `web/lib/metricsData.ts`.
**Interfaces:** Consumes `metrics.ts`, `useSettings`, `fetchAll`. Produces `loadMetricsData(includeTest = false): Promise<{leads: LeadRow[]; touches: TouchRow[]; costs: CostDay[]; runs: RunRow[]}>` (leads `id,place_id,batch_id,batch_no,status,vector,signal_led,owner_name,owner_email,email_verified,reject_reason,created_at,booked_at`; sent touches only; `cost_daily`; `batches` id, name, created_at; test rows dropped unless `includeTest`).
- [ ] **Step 1:** Loader with a stable `order` on every `fetchAll` (`cost_daily` by day, provider, run_id).
- [ ] **Step 2:** Page, spec 7.4 in order: Batches of 100 (cells "k of n (p%)", `n/a` for null, allocated spend as dollars plus credits per provider, cost per verified owner and per reply via `perUnit`, a "living number" note), the static Notion rows under it; Money (per provider for the range, the four buckets); History (grain select, from and to dates, previous range beside it, undated line); Angles (batch select); Where leads die; the old per-run funnel and cost tables collapsed, unchanged. A note states: batches use the Touch 1 cohort, history uses event dates, the page is UTC.
- [ ] **Step 3:** `cd web && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 4:** Commit `feat: metrics page`.

### Task 6: Home (Group B)
**Files:** Replace `web/app/page.tsx` (the redirect); Create `web/lib/homeData.ts`.
**Interfaces:** Consumes `home.ts`, `metrics.ts`, `loadOutreachBatches` and `batchBase` from `web/lib/batches.ts`, `useSettings`. Produces `loadHome(now: Date, includeTest = false): Promise<{yesterday: {scraped: number; owners: number; numbered: number; touch1: number; followups: number}; counts: HomeCounts; monthSpend: Spend; geminiSince: number; autopilot: string}>`.
- [ ] **Step 1:** Loader: yesterday's leads by `dayRange(now, 1)` on `created_at` (scraped, `isOwner`, `batch_no` not null) and sends by `sent_at` in the same range; counts from rows filtered with `isTestLead` (selected and not approved; touches `drafted` split Touch 1 versus follow-ups; touches `approved` or `scheduled` while `sending_on` is false; leads `replied` whose last sent touch outcome maps to `look` via `replyBucket`; mailbox `paused_reason`); `cost_daily` since the earlier of the month start and `credit_balance_as_of` for the month spend and the Gemini spend.
- [ ] **Step 2:** Page: next-action card, yesterday block (date shown, "local time"), open batch and autopilot state, budget meter and credit line with warnings (warn pill when `creditStatus.warn` or `pct >= 100`), links to Metrics and Replies.
- [ ] **Step 3:** `cd web && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 4:** Commit `feat: home page`.

### Task 7: Replies page (Group B)
**Files:** Create `web/app/replies/page.tsx`, `web/lib/repliesData.ts`; Modify `web/app/outreach/page.tsx`.
**Interfaces:** Consumes `replyBucket`, `gmailThreadUrl`, `setOutcome`, `markBooked`. Produces `loadReplies(includeTest = false): Promise<{rows: ReplyRow[]; address: string | null; checkedAt: string | null}>` with `ReplyRow = {lead_id; name; owner_email: string | null; status; batch_no: number | null; vector: string | null; lane: string; touch_no: number; outcome: string | null; outcome_at: string | null; thread_id: string | null}` (touches with an outcome, joined to leads, plus status `replied`, `booked`, `unsubscribed`, `bounced` leads; mailbox address and `replies_checked_at`).
- [ ] **Step 1:** Loader and page per spec 7.6: five sections by `replyBucket`, actions only in "needs a look" and "positive", "date not recorded" when `outcome_at` is null, thread link or the bare thread id when missing, header "replies last read".
- [ ] **Step 2:** In `web/app/outreach/page.tsx` remove the "Replies and outcomes" block and the `setOutcome` and `markBooked` imports; replace the stale first paragraph with: "Sending is started and paused on the Send page. Edit drafts in the OS: the database text is what goes out." Keep mailboxes, drafts waiting, sequences.
- [ ] **Step 3:** `cd web && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 4:** Commit `feat: replies page`.

### Task 8: Per-lead panel (Group B)
**Files:** Create `web/components/LeadActivity.tsx`, `web/lib/leadActivity.ts`; Modify `web/app/leads/page.tsx` (render inside the open detail).
**Interfaces:** Produces `loadLeadActivity(leadId: string): Promise<{spend: Spend; touches: {touch_no: number; status: string; sent_at: string | null; outcome: string | null; outcome_at: string | null}[]}>` using `spendFrom` over that lead's `cost_log` rows.
- [ ] **Step 1:** Loader and `<LeadActivity leadId={string} />` (loads on mount, table by provider: units and dollars, label "recorded against this lead; scrape-time Apify is per run", a touch line each).
- [ ] **Step 2:** `cd web && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 3:** Commit `feat: lead activity panel`.

### Task 9: Verify under RLS (Group C, needs Task 1 applied)
**Files:** Create `web/scripts/verify_metrics.mts` (header and login pattern of `verify_batches.mts`, including the `autopilot_on` refusal and cleanup in `finally`).
- [ ] **Step 1:** Seed with the admin client: batch `TEST metrics verify`; leads `TEST_mv1..6` (statuses sent, sent, replied, bounced, booked, drafted; `batch_no` null; one created at yesterday noon local; one verified owner); Touch 1 sent rows with `sent_at` today and yesterday; `cost_log` rows (one with `batch_id`, one with `lead_id` only, apify and hunter). Sign in by magic link.
- [ ] **Step 2:** Assert (labelled `check`, `ok` or `FAIL`): `cost_daily groups the seeded rows by UTC day, provider and run`; `cost_daily attributes a lead-only row to the lead's run`; `loadMetricsData drops TEST rows by default`; `loadMetricsData(true) returns the seeded leads, sent touches and costs`; `setOutcome stamps outcome_at through the web write path`; `markBooked stamps booked_at`; `loadReplies buckets the seeded replied, bounced and booked leads and carries outcome_at and the thread id`; `loadHome counts the seeded yesterday lead as scraped and as a verified owner`; `loadHome counts the seeded drafted touch`; `loadLeadActivity returns the lead's spend by provider and its touches`. `includeTest` also returns real rows, so compare counts against a baseline read before seeding and find the seeded rows by `place_id`.
- [ ] **Step 3:** Run `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_metrics.mts`. Expected: every line `ok`, no FAIL; seeded rows deleted (re-select to prove). Then `scripts/verify.mts` (autopilot paused only). Expected: still passes.
- [ ] **Step 4:** Commit `test: metrics verify script`.

### Task 10: Real browser verification (Group C, owner present for login)
- [ ] **Step 1:** `cd web && npm run dev`; log in by magic link; use the Claude-in-Chrome or Playwright tools.
- [ ] **Step 2:** With the real data: Home and Metrics show `n/a` for every rate and per-reply cost (nothing sent yet) and no crash; Metrics fill for one batch number equals the count on `/leads` filtered the same way (compare by hand, record both numbers); the four spend buckets add up to the Money total; Replies renders empty sections; Settings price keys save and change the priced dollars; screenshots of Home, Metrics, Replies, a Leads detail.
- [ ] **Step 3:** Gmail link: take one real thread id the owner supplies (or a TEST row with a rehearsal thread), open the `/replies` link, confirm it lands on that thread. If it does not, show the bare thread id and record the finding.
- [ ] **Step 4:** Delete every TEST row. `git status` shows only Plan 6 files (Codex files untouched).

### Task 11: Nav and docs (Group C)
**Files:** Modify `web/app/layout.tsx` (nav: Home first, Replies after Send, Dashboard becomes Metrics), `CLAUDE.md` (one bullet in Commands: pages Home, Metrics, Replies and `0016`), `docs/HANDOFF.md` (section 0 (a) Plan 6 row and the file map row for `web/app/dashboard/page.tsx`), `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (row 6 BUILT), `docs/runbooks/cloud-runner.md` (line 122: `/dashboard` to `/metrics`).
- [ ] **Step 1:** Edit; keep each to a few lines. Commit `docs: plan 6`.

## Hard gates (stop and ask the owner)
1. Applying migration `0016` to the real database (Task 1 Step 4). It is additive; no backfill of existing rows.
2. Any verify script or db test while `autopilot_on` is true; TEST rows only, never real batches or real settings values.
3. Any VM deploy: none is planned (triggers capture the timestamps; the worker is unchanged).
4. Any paid call: none is planned. Entering real credit prices is the owner's act in Settings.
5. Any real send to exercise Replies (the real send is on hold); use TEST rows.

## Self-review
Spec coverage: Home (Tasks 4, 6), Metrics with batches of 100, money, history, angles, where leads die (3, 5), Replies (4, 7), per lead (8), budget meter and credit warning (4, 6), event timestamps and `cost_daily` (1), prices (2), RLS and browser proof (9, 10), docs and nav (11). Owner decision 3 (Notion rows) is `HISTORY` in Task 3; decisions 1, 2, 4, 5 change defaults only (price keys exist at 0; denominator is `delivered` in `cohort`; the assistant and the hypothesis note are not built). Type consistency: `Spend` is a provider-keyed record everywhere (Tasks 3, 4, 5, 6, 8); `includeTest` is the only loader flag. Findings to relay: `/batches` outreach cards count leads by current status, so "sent" drops when a lead replies (Metrics uses the Touch 1 cohort instead); `monthly_budget_pkr` and the credit settings had no reader; the Outreach page text "edit them in Gmail" is stale and is fixed in Task 7.
