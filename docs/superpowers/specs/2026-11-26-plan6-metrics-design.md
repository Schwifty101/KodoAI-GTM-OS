# Plan 6 design: metrics, Home and Replies (2026-11-26)

Status: draft for owner review. Builds on the operating-layer design (`2026-11-12-gtm-os-operating-layer-design.md`, sections 2.1, 2.8, 5, 10, 16) and roadmap row 6. Where this is silent, those and `CLAUDE.md` rule. Docs only: nothing was built or queried to write it (a live autopilot runs on the real database); counts quoted come from existing docs.

## 1. Intent and why
The owner tests his outreach one batch of 100 at a time and changes strategy between batches. After each batch he needs to see: how many were sent, bounced, replied and booked; what the batch cost per verified owner and per reply; and which angle did what. Today the OS shows counts, not rates; spend is split across three places; a reply, a bounce or a booking has no date, so there is no history; Home does not exist (`/` redirects to `/leads`); and the monthly budget and the Google credit are settings that no page reads. Plan 6 closes that gap with no new paid call and no change to the worker.

## 2. What already exists and what remains (checked 2026-11-26 against code at `29f2d41`)
| Piece (roadmap row 6) | Status | Evidence |
|---|---|---|
| Funnel and cost per scrape run: scraped, kept, verified, signalled, drafted, sent, bounced, replied, positive, booked; Apify per lead and per verified email; Hunter credits per verified email | BUILT | `web/app/dashboard/page.tsx`, view `batch_metrics` (`0006`), `tests/test_metrics.py`. Counts and ratios between columns, no rates by batch of 100, no dates |
| Batch of 100 (`leads.batch_no`): fill (with `batch_base`), leads by status, spend recorded against its leads | BUILT | `/batches` (`web/lib/batches.ts`, view `batch_no_spend` `0012`). Status counts, so "sent" drops when a lead replies; spend is lead-linked only, scrape-time Apify is not (comment in `0012`) |
| Spend today and month per provider against daily caps | BUILT | Settings "Spend" (`spend_summary`, `0007`) |
| Mailbox sent today, 7-day sent and bounce percent | BUILT, mailbox-wide | `/send` |
| Reply and bounce classification, mark positive, negative, booked | BUILT | `gtm/replies.py`; `web/app/outreach/page.tsx` "Replies and outcomes" (no date, batch, angle or Gmail link) |
| Home | NOT BUILT | `web/app/page.tsx` is `redirect("/leads")` |
| History by day, week, month, quarter | NOT BUILT, and not derivable | Timestamped events today: `touches.sent_at`, `cost_log.created_at`, `leads.created_at`, `suppression.created_at`. `touches.outcome` and `leads.status = booked` carry no time |
| Per-batch send, bounce, reply, booked rates | NOT BUILT | only counts exist |
| Cost per verified owner and per reply by batch of 100 | NOT BUILT | needs attribution of scrape-time and failed-lead spend (section 7.3) |
| Per-angle (vector and lane) response | NOT BUILT | `leads.vector` and `leads.signal_led` exist; no page groups by them |
| Budget meter against `monthly_budget_pkr` | NOT BUILT | the key and `pkr_per_usd` have no reader outside the Settings form |
| Credit warning (under 20 percent or 14 days) | NOT BUILT | `gtm/budget.py credit_remaining_usd` is Python only |
| Replies page | NOT BUILT as a page | block inside Outreach only |
| Per-lead cost and touches | NOT BUILT | Leads detail shows evidence only |
| Fetch failures by reason | NOT POSSIBLE | nothing logs a fetch failure; out of scope |

Plan 6 is therefore partly built (the per-run funnel, lead-linked batch spend, caps, classification). The rest is this plan.

Data reality that shapes it: the first real send is ON HOLD (HANDOFF section 0 (a)), so outcome metrics (send, bounce, reply) have no real rows yet; cost and yield data do (autopilot is spending now). The only real outcome history is Notion Batch01-03 in `docs/spikes/sending_history.md` (218 Touch 1 sends, 12 bounces, 4 negative, 2 out of office, 0 positive).

## 3. Goals
1. **Home** at `/`: yesterday's scraped leads, how many of those became verified owners, how many were numbered into a batch, emails sent yesterday; one next action ("8 drafts waiting for review"); the open batch fill and autopilot state; month-to-date budget meter; the credit warning.
2. **Metrics** page (replaces Dashboard): batches of 100 with rates and cost per verified owner and per reply; money per provider; history by day, week, month, quarter with a custom range and the previous period beside it; per-angle response; where leads die.
3. **Replies** page: every reply, bounce, opt-out and booking with its date, batch, angle, touch and a Gmail link; the existing positive, negative and booked actions move here.
4. **Per lead**: cost recorded against the lead and its touches, in the Leads detail.
5. Every number states its basis; none is invented; empty data shows "n/a", never 0 percent or NaN.

## 4. Non-goals and anti-goals
- No open or click tracking, no charts library (tables and text), no new paid call, no worker change, no VM deploy.
- No reply text stored, no positive-reply assistant (roadmap candidate, undecided), no un-suppress button (anti-goal: never edit suppression rows from a UI).
- No copy-variant tags on drafts and no per-batch hypothesis field: both belong with the parked email strategy (`docs/NEXT-email-strategy.md`).
- No fetch-failure metric (no data), no backfill or edit of existing rows, no PKR hard cap (caps stay in `gtm/budget.py`; the meter only displays).
- Anti-goals: a metric that includes TEST_ or REHEARSAL_ rows; a rate computed from a different population than its count; a made-up price, threshold or default shown as fact; spend that silently vanishes from a total.

## 5. Constraints
- `CLAUDE.md` governs. Supabase Postgres is the only database; every table and view under RLS (`security_invoker` views, the `0006` and `0012` pattern); the browser uses the publishable key and the operator session; the secret key stays script-side.
- Plan 8 pattern for the web: pure logic in `web/lib`, unit-tested with `tsx` scripts and no database; loaders in a separate file; DB behaviour proven by a `verify_*.mts` script under RLS; a real browser run before "verified".
- Tests use `TEST_` place ids and batch names starting `TEST` only (`REHEARSAL_` for manual rows). One pytest process at a time. The verify scripts refuse to run while `autopilot_on` is true unless `ALLOW_LIVE_AUTOPILOT=1` (as `verify_batches.mts` does).
- Real leads only: `place_id` not starting `TEST_` or `REHEARSAL_` (the `gtm/send.py is_test_lead` rule), runs not named `TEST...` or `REHEARSAL...`.
- Prices are never defaulted to a guess: a credit with no price counts as credits, not dollars.
- No emojis, no invented numbers in docs or UI.

## 6. Approaches considered
- **A. SQL-first**: views for per-batch cohorts, periods and attribution. One source of truth, fast. But attribution and period maths in SQL can only be tested against the real database, and every metric change becomes a migration the owner must approve while autopilot runs.
- **B. Browser-only over raw rows, no migration**: simplest, and the repo already does it (`web/lib/batches.ts`). But replies, bounces and bookings carry no time, so history is impossible, and `cost_log` (a row per Serper query and LLM call) is the wrong thing to ship raw to a browser.
- **C. Python snapshot job writing a metrics table**: a new table, job kind, staleness and a VM deploy, for nothing a view does not give.
- **D. Hybrid (recommended)**: the smallest SQL that fixes what is missing, everything else pure TypeScript. SQL: two event timestamps stamped by triggers (so no Python or web write path changes and no VM deploy) and one dumb aggregate view `cost_daily`. TypeScript: cohorts, rates, attribution, periods, angles as pure functions over rows read with `fetchAll`. Why: it is the repo's own pattern, the logic is unit-tested offline, the migration is additive, and the worker is untouched.

Cost attribution has three options. Lead-linked only (today's `batch_no_spend`) ignores every failed lead, which is most of the spend. A fill-window split needs a `selected_at` that does not exist. **Pro rata per scrape run (recommended)** uses the `batch_id` and `lead_id` that every lead pass already logs (`spend_context` in enrich, signals, select, draft, redraft, sheet-verify, replies).

## 7. The design
### 7.1 Definitions (one source: `web/lib/metrics.ts`)
| Term | Rule |
|---|---|
| Verified owner | `owner_email is not null and email_verified` (same as `batch_metrics.enriched`; `CLAUDE.md` "Enriched") |
| Batch of 100 | `leads.batch_no`; fill = OS leads plus `batch_base` (Notion leads outside the OS: no cost, no outcomes) |
| Sent cohort | leads of the batch with a Touch 1 whose status is `sent` |
| Bounced | cohort leads with status `bounced` |
| Replied | cohort leads with status replied, unsubscribed or booked, or any touch outcome positive, negative, other, opt_out (the `batch_metrics.replied` rule). Auto-replies are never recorded, so never counted |
| Positive, Booked | outcome positive or status booked; status booked |
| Rates | bounce = bounced of sent; reply, positive, booked = k of delivered (sent minus bounced). Always printed as "k of n (p%)"; n = 0 prints "n/a" |
| Angle | `leads.vector` and lane (`signal_led` true = signal-led, else relevance-led) |
| Money | recorded dollars where `cost_log.usd` is set (apify, gemini, harvest); credits where only `units` are logged (hunter, hunter_import, prospeo, serper, serper_maps); groq stays tokens and never becomes money. Priced dollars = recorded + credits times the optional price settings (0 = unpriced) |

### 7.2 Data changes (migration `0016`, additive, owner gate)
- `touches.outcome_at timestamptz`: a trigger sets it to `now()` the first time `outcome` becomes non-null (insert or update) and never overwrites it. Covers the Python reply pass and the web `setOutcome` with no code change. Outcomes already stored stay null: they count in every cohort rate and show as "undated" in the history.
- `leads.booked_at timestamptz`: same trigger rule on status becoming `booked`.
- View `cost_daily(day date, provider text, run_id uuid, units numeric, usd numeric)`: `cost_log` grouped by UTC day, provider and `coalesce(cost_log.batch_id, leads.batch_id)` (a lead-only row follows its lead's scrape run); `security_invoker`. It does not filter test data: the TypeScript drops test runs (so the verify script can read its own TEST rows).
- Three optional settings in the "API prices" group: `price_hunter_usd_per_credit`, `price_prospeo_usd_per_credit`, `price_serper_usd_per_credit`, default 0.0 (unpriced), never negative. Hunter and Serper credits do not return dollars today and no Hunter plan is bought, so no default is invented.

### 7.3 Cost attribution (pro rata per scrape run)
Every cost row belongs to a run (its `run_id`) or to nobody. Each run's total spend is split equally over that run's verified owners; a batch of 100 carries the sum of the shares of its numbered leads. Result: a batch's cost per verified owner is the weighted average of its source runs' cost per verified owner, and it includes the failed leads, which are most of the spend.
Four buckets must add up to total spend (the conservation test): spend allocated to numbered leads (per batch), allocated to verified owners not yet numbered, in runs with no verified owner yet ("not allocated"), and rows with no run ("no batch or lead"). All four are printed. Cost per reply = allocated spend of the batch / its replied count, "n/a" at zero replies. The numbers move as enrichment and drafting continue ("living"); the page says so.

### 7.4 Metrics page (`/metrics`)
Sections, top to bottom: (1) **Batches of 100**: batch, fill, sent, bounced, replied, positive, booked, allocated spend (dollars and credits), cost per verified owner, cost per reply; below them static Notion rows Batch01-03 from `docs/spikes/sending_history.md` (sent, bounced, negative, out of office, positive; labelled "Notion log, no per-lead data"; Batch03's OS row is separate and never summed with its Notion row). (2) **Money**: per provider for the chosen range (recorded dollars, credits, priced dollars) and the four attribution buckets. (3) **History**: grain (day, week Monday-start, month, quarter), range, and the previous equal-length range beside it; columns: scraped (by `leads.created_at`), verified owners from that cohort, Touch 1 sent and follow-ups sent (`sent_at`), bounces, replies (`outcome_at`), booked (`booked_at`), recorded spend, cost per verified owner (period spend / that period's cohort owners; approximate, enrichment can finish later, labelled). All buckets are UTC like the caps and `spend_summary`. History holds counts and money only; rates live in section 1, where the cohort is clean. (4) **Angles**: vector by lane, with a batch filter: sent, bounced, replied, positive, booked as "k of n". (5) **Where leads die**: counts by `reject_reason`, no_buyer named versus no owner found, signalled-not-selected reasons. (6) The old per-scrape-run funnel and cost tables, collapsed (the `batch_metrics` view stays; `/batches` also reads it).

### 7.5 Home (`/`)
Yesterday is the browser's previous local calendar day (operator-configured time zone, default the browser's, per operating-layer 15.9); the Metrics page is UTC, and both say so. Next action is one line chosen by a fixed order: replies needing a look, mailbox paused, approved emails waiting while sending is off, follow-ups waiting for approval, drafts waiting for review, selected leads waiting for approval, else the open batch fill. Warnings listed separately: Google credit under 20 percent or under 14 days or ended (remaining = `credit_balance_usd` minus Gemini dollars since `credit_balance_as_of`, the `budget.credit_remaining_usd` rule), budget over 100 percent, autopilot paused with its reason. Budget meter: month-to-date priced spend against `monthly_budget_pkr / pkr_per_usd`; Gemini joins the meter only after the Google credit has ended (the credit pays for it until then, operating-layer 12); unpriced credits are listed as credits, not guessed.

### 7.6 Replies page (`/replies`)
Sections: needs a look (replied, outcome empty or other), positive (open), booked, declined (negative, opt-out, unsubscribed), bounced. Row: business, owner email, batch number, angle, touch number, date from `outcome_at` ("date not recorded" when null), Gmail thread link, and for the first two sections the existing Positive, Negative and Mark booked actions. Header shows when replies were last read (`mailboxes.replies_checked_at`). The Gmail link format `mail.google.com/mail/?authuser=ADDRESS#all/THREADID` is unverified until the browser run. Outreach loses its reply block and its stale line ("edit them in Gmail"; the database text is what goes out) and keeps mailboxes and sequences.

### 7.7 Leads detail
Opening a lead loads its `cost_log` rows (by provider: units, dollars) and its touches (touch, status, sent time, outcome, outcome time), labelled "recorded against this lead" (scrape-time Apify is per run, not per lead).

### 7.8 Testing
Pure logic by `tsx` scripts (`metrics_unit.mts`, `home_unit.mts`, run under two process time zones); migration by `tests/test_metrics_events.py` (db, TEST rows); loaders by `web/scripts/verify_metrics.mts` under RLS; pages by a real browser run. Real batches are never written.

## 8. Left to the builder
Exact SQL spelling of the triggers and view (the semantics above are fixed); column order and spacing; text bars versus plain numbers; how a page batches its reads (one load per visit, no polling); copy of the explanatory notes; whether the history range defaults to the last 8 periods; pagination of long tables.

## 9. Gates
Applying `0016` to the real database needs the owner's yes. Verify scripts and db tests only with autopilot paused, TEST rows only. No VM deploy. No paid call. No change to real settings values. The real send stays on hold: Replies is exercised with TEST rows, never by sending.

## 10. Calls made (mine; correct any)
Cohort rates use delivered as the denominator for reply, positive and booked; history is event-based and rate-free; UTC for the Metrics page and local time for Home's "yesterday"; the Dashboard route is renamed Metrics and Outreach keeps mailboxes and sequences; the 20 percent credit base is the entered `credit_balance_usd`; no small-sample flag (it needs a threshold nobody has measured), only "k of n"; the Notion rows are a typed constant with a unit test pinning the doc's totals.

## 11. Owner decisions (each has a recommendation; the plan works with the default)
1. **Price the credit providers?** Hunter, Prospeo and Serper log credits, not dollars, so cost per verified owner and the PKR meter only count Apify, Harvest and Gemini dollars until a price is entered. Recommend: add the three price settings (default 0) now; enter Serper only when you confirm the pack price, Hunter after the plan decision.
2. **Reply-rate denominator.** Recommend delivered (sent minus bounced), with "sent" shown beside it. Say so if your Notion reports used sent.
3. **Notion Batch01-03 as history rows.** Recommend yes: static rows from `sending_history.md` so trends start at the first campaign (Batch03's OS row shown separately). Confirm those counts are still right.
4. **Positive-reply assistant** (Gemini drafts, you approve). Recommend not until the OS holds one real positive reply; history shows 0 of 218.
5. **Per-batch hypothesis note** ("signal-led only, subject B") on each batch row. Recommend not now: keep it in Notion and add it when the email strategy un-parks; the angle table already separates vector and lane.
