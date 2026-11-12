# HANDOFF: KodoAI GTM OS (updated 2026-11-13, branch `plan3-scrape-batches`; section 0 is the current state, sections 1-11 were written 2026-11-11 and patched where stale)

Read this first, then `CLAUDE.md`. Everything here was read from the repo or established in the building session; anything not checked is marked **unverified**.

## 0. Where things stand (end of session 2026-11-12)

Single "start here". Checked against `git log`, code and docs on 2026-11-12. The 509-test figure comes from the coordinator's last full run and was not re-run for this doc. Nothing was queried from the database for this section; DB-dependent numbers are marked unverified.

### (a) Status

| Area | Status |
|---|---|
| Passes scrape, clean, enrich, signals, select | Built; ran live on the Houston batch (2026-11-11) |
| Finders `site`, `search`, `research`, `prospeo` (default); `hunter`, `harvest` (opt-in) | Built; measured live (`docs/spikes/owner_routes.md`) |
| LLM: Vertex Gemini primary, Groq fallback | Built; Gemini ran the Houston batch. Fallback behavior when the Google credit ends: **never run live** |
| **Plan 1 (foundation): FINISHED and merged to `main` (PR #1)**, task reviews, whole-branch final review, fix wave `e23cb15` plus scoped re-review, minors waves `4add850` and `fb8bd7f` | Built. Settings store (`gtm/settings_store.py`), budget caps and paid-Gemini gate (`gtm/budget.py`), `jobs` table + worker (`gtm/jobs.py`, `gtm/worker.py`), Settings page, batch+lead on every `cost_log` row, `spend_summary` view; migrations 0007 and 0008 applied to the real project. Full suite **509 passed** (~5-6 min, hits the real Supabase project) |
| Local reply classifier (`gtm/replies.py`, `a9be7dc..4d67ceb`) | Built, unit-tested; never run on real replies. See (c) |
| UI: Leads, Review, Outreach, Dashboard, Login, Settings | Built; `verify.mts` checks write actions under RLS |
| Worker against a real queue | Runs on the VM (smoke test: a `send` job drained and failed as designed; kill -9 and VM reset recovery). A real `clean` job ran on the VM 2026-11-12 (a no-op on the already-cleaned Houston batch, no restarts). A heavy pass (enrich, signals) has not run there, so RAM under load is **unverified** |
| Pass `draft`, `followups`, `send`, `replies` | Built, **not run live**: no draft created, Gmail `send_draft`, thread and bounce reading in a real batch, Touch 2/3 threading unverified |
| Cloud runner (GCP VM, Secret Manager) | **Plan 2 built 2026-11-12** (branch `plan2-cloud-runner`): VM `gtm-worker` (e2-micro, us-west1-b) runs the worker under systemd; migration 0009 applied. Runbook: `docs/runbooks/cloud-runner.md`. Verified: smoke test, kill -9 and VM reset recovery. **Not verified:** a real unattended pass and RAM peak under it (being finished 2026-11-12, see (f)), Gmail send from the VM (Plan 4) |
| **Plan 3a (scrape and batches, backend): BUILT 2026-11-13** on branch `plan3-scrape-batches` (Tasks 1-7; PR to be opened by the coordinator) | Migration 0010 applied to the real project (`coverage` table, `leads.batch_no`, `leads.tz`). Coverage seeded: 1285 tiles, 201 metros (`gtm/data/metros.csv`, Census-ranked via a Wikipedia list; tile names for added metros written from memory, not checked against Google Maps; Houston, Sugar Land, The Woodlands marked done by hand). `tz-backfill` set tz on 59 of 60 leads (one has no city/state). Passes `walk`, `seed-coverage`, `tz-backfill`; `select` numbers batches of 100. Defaults from `docs/spikes/tile_tuning.md`: `walk_queries='med spa,aesthetics clinic'`, `walk_max_places=40`, `walk_escalate_at=0.8` (dense tiles saturate the cap of 40; deeper caps untested). Fetch fallback: `docs/spikes/fetch_fallback.md` |
| First live tile (VM worker, 2026-11-13) | New York / Manhattan, 2 queries, 80 places, 71 new leads, 9 already known, saturated; clean kept 48, rejected 23 (15 category, 3 duplicate domain, 2 closed, 2 no website, 1 chain); 69 of 71 have a tz; $0.4004 (2 apify rows); no duplicate place ids; job `done`, worker unchanged |
| Plan 3b (Scrape & Coverage and Batches pages) | Not started. Plans 4-6 not written, not built |
| Email copy and angle strategy | **Parked**: `docs/NEXT-email-strategy.md` |

### (b) Houston batch e11d97b6-41a0-4957-8d3d-6b1728f74d90 (as of the 2026-11-11 measurement; **unverified**: not re-queried)

60 scraped ($0.30), 52 cleaned (87%), 9 enriched, 8 signalled and **selected, awaiting owner approval on the Review page**; nothing drafted or sent. Names found for ~62% of cleaned; verified owners ~15-17%. Owner-confirmed corrections: the researcher's name for Miliv Med Spa was wrong (cleared); Jamie Marcelle (joinskindeep.com) and Isam Balat (myplazawellness.com) are the right owners but no email passed the rule (kept `no_buyer` with saved names). The first real send of the 8 selected leads has NOT happened.

### (c) Local reply classifier (owner request; `gtm/replies.py`)

| Item | Behavior |
|---|---|
| Order | Rules first: bounce, auto-reply (headers/subject), explicit opt-out ("don't call me" counts). Then `local_kind`. Then the model (Gemini, Groq fallback) |
| `local_kind` negative | ONLY a bare decline of at most 6 words matching the allow-list `NEG_FULL` ("No", "Not interested", "No thanks", "We're all set", ...). Anything longer or mixed goes to the model |
| `local_kind` positive | Clear interest cue (`POS_CUE`) with no decline cue and no deferral cue; otherwise None |
| Negative outcome | Suppression rows (lead email, replier address, business domain unless free-mail) with reason `not-interested`; lead stays `replied`, touch outcome `negative` |
| Priority | A later positive in the same thread outranks an earlier negative (`PRIORITY` negative 2.5) |
| Signature stripping | Tried and DELETED (`4d67ceb`): a decline plus "Sent from my iPhone" goes to the model, which is safe |
| Cost | Reply-classification model calls carry the lead id in `cost_log` (`spend_context`) |
| Why so conservative | 5 fix rounds: a wrong "negative" suppresses a lead permanently |
| NOT built | Gemini continuing the conversation with positive replies (positives are only flagged). A drafted reply for owner approval is a **proposed** Plan 4 addition (not decided) |
| NOT built | UI to remove a wrongly suppressed row: today it is a **database edit** (delete the `suppression` rows, reset the lead status by hand) |
| Accepted quirk | The greeting name slot in `NEG_FULL` takes any single word, so "Hello maybe no" counts as a bare decline (harmless) |

### (d) Branch and merge state

Plan 1 (branch `gtm-os-build`) was **merged to `main` by the owner as PR #1** (`ce73579`); `main` is pulled locally. Plan 2 lives on branch `plan2-cloud-runner` (commits `5f42a4f..54e4497`: heartbeat, systemd unit and secret loader, bootstrap and deploy scripts, latency script, deploy fixes, runbook, handoff). It is being pushed for a PR; whether that PR is open or merged is **unverified**. Uncommitted `web/next-env.d.ts` and `web/tsconfig.tsbuildinfo` are regenerated by `next dev`: ignore or `git checkout` them.

### (e) Plan set and what is next

| Doc | Status |
|---|---|
| `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` | Six plans; order 1, then 2 and 3, then 4, then 5 and 6 (5 can move earlier) |
| `docs/superpowers/plans/2026-11-12-plan1-foundation.md` | **BUILT**, commits `0c53f4b..4d67ceb` |
| `docs/superpowers/plans/2026-11-12-plan2-cloud-runner.md` | **BUILT** 2026-11-12 (branch `plan2-cloud-runner`): VM `gtm-worker` live, Secret Manager, `Restart=always`, heartbeat lease (migration 0009 applied). Only the first real unattended pass and the budget alert are still being finished: see (f). Free-trial decision made (below) |
| Plan 3 scrape and batches | **3a BUILT 2026-11-13** (coverage walk, batches of 100, time zones, fetch fallback; branch `plan3-scrape-batches`). 3b open: Scrape & Coverage and Batches pages; retry-later job not built |
| Plan 4 drafts and sending | Drafts in the database, bulk edit, send scheduler, Pending follow-ups, send via the Gmail API. Candidate (proposal, undecided): positive-reply assistant that drafts a reply for the owner to approve |
| Plan 5 sheet import and manual queue | Color rule, Manual queue tab |
| Plan 6 metrics, Home, Replies | History, Home, Replies pages |

**Google Cloud free-trial decision: DECIDED 2026-11-12.** The owner upgraded the account to full pay-as-you-go before the trial end (2027-02-09), so nothing is marked for deletion. Budget alert created 2026-11-12: "GTM OS monthly", $20 USD, alerts at 50, 90 and 100 percent (alerts warn, they do not cap). `allow_paid_gemini` (off by default) stays the only Gemini spend guard. Costs: external IPv4 about $3.65/month; the VM itself is free tier (no end date, Google may change it with 30 days notice); see the runbook.

### (f) Open items for the owner

| # | Item |
|---|---|
| 1 | Done 2026-11-12: budget alert, full-account upgrade, merge menu, trial decision (row kept so item numbers stay stable) |
| 2 | First real unattended pass on the VM (runbook open items; suggested `clean` on the Houston batch, no paid API; record the RAM peak). Done 2026-11-12 for `clean` (no-op, no restarts); a heavy pass and its RAM peak are still **unverified** |
| 3 | Approve the 8 selected Houston leads on the Review page, then approve each paid/send step of the first real send |
| 4 | Hunter plan (buy only when the OS can safely run a campaign) |
| 5 | Re-pull Notion Batch03 and `import-history` before each batch |
| 6 | Prospeo (83 credits) and Apify free credit renew/end 2026-11-24; no paid Apify top-up without asking. Apify balances left 2026-11-13: about $4.7 and $4.68; month spend so far about $5.8 |
| 9 | Daily schedule (`walk_schedule_enabled`) is OFF: the owner decides when to turn it on. The daily Apify cap ($2 default, no stored row) was raised temporarily for the spike, the live tile and the fallback test, and restored each time |
| 7 | Live `weekly_target=200` row in the `settings` table equals the default (left by an old unguarded test upsert): delete if the owner never set it |
| 8 | Brainstorm visual-companion server dir `.superpowers/brainstorm/36501-1794413655/state/` had `server-stopped` at last check; if a server runs, stop it with the brainstorming skill's `scripts/stop-server.sh` |

### (g) Owner decisions, all 2026-11-12 (design sections 15 and 16; section 15 items are assistant calls the owner has not individually confirmed)

- UI: Home plus tabs; pages Home, Batches, Scrape & Coverage, Leads, Review, Drafts, Send, Replies, Manual queue, Metrics, Settings.
- Batches of 100 verified, selected owners, filling over several days; a lead's batch is fixed once assigned.
- Runner: worker on an always-on Google Cloud VM, us-west1 (created 2026-11-12; latency to Tokyo DB median 162 ms from the VM vs 230 ms from the Mac). UI and schedule add jobs; keys and Gmail login go to Secret Manager.
- Sending: weekdays, recipient-local US time, random times in a window (assumed 9 to 4), start 20 a day and ramp +5 a day to 40 per mailbox (RAMP_STEP=5; the design-doc typo was fixed in `aa4d0f0`). Cadence Day 0/3/7. Auto-pause at >5% bounce over >=40 sends.
- Follow-ups drafted automatically but each approved by the owner in a **Pending follow-ups** list on the Send page; replied/bounced leads skipped and listed as flagged.
- Sheet import (Plan 5): any green cell in a row = sent (suppress), any red = dropped, uncolored = potential lead; plus a **Manual queue** tab for ContactOut lookups (about 5 a day).
- Retry-later job for named-but-no-email leads when credits reset. Metrics history by day, week, month, quarter; budget meter.
- **Budget: 25,000 to 30,000 PKR a month at 276 PKR per USD is a hard constraint.** Weekly target 200 verified owners while the Google credit lasts, then sized to the budget; both are settings.
- Google Cloud credit: $298 of $300 left on 2026-11-12, ends **2027-02-09**. **No paid Gemini spend without the owner confirming** (Settings switch "Allow paid Gemini", off by default; Groq fallback otherwise).
- Hunter plan: buy only when the OS can safely run a campaign. Second mailbox: after Batch04 or when there is enough data. Workspace plan is paid.
- Email copy and angle strategy PARKED: `docs/NEXT-email-strategy.md`.
- Sending change (design 15.1, assistant call): Plan 4 sends the stored draft text via the Gmail API. **Until Plan 4 lands, "edit drafts in Gmail; the Gmail draft is what goes out" is true.**

### (h) Rulings made while executing Plan 1 (the ledger was deleted after the final review; git history is the record)

| # | Ruling |
|---|---|
| R1 | Parallel implementers in one tree with path-scoped commits and a DB-test lock (`/tmp/gtm-pytest.lock`) |
| R2 | `tests/conftest.py` autouse patches `gtm.budget._cost_rows` and `setting` so unit tests never hit the DB |
| R3 | Stay on `gtm-os-build`, no worktree |
| R4 | Migration 0007 applied to the real project via MCP (new tables only) |
| R5 | Sonnet for implementers and reviewers, opus for the final review |
| R6 | Wave C dispatched while Task 3's review was in flight |
| R7 | Credit counts as ended ON 2027-02-09 (`today < credit_end_date`), fail closed (cost if wrong: Gemini falls back to Groq one day early) |
| R8 | `run_enrich` lets `BudgetExceeded` propagate; CLI `main()` prints "budget cap reached" and exits non-zero; the worker maps it to `paused_budget` |
| Later (git messages) | Stale-job requeue fails a job after 3 attempts and Ctrl-C marks it `cancelled` (`e23cb15`); `cmd_scrape` checks the budget before creating a batch, `finish()` only ends `running` jobs, `claim_job` has a fixed `search_path` (migration 0008) (`fb8bd7f`); local negative is an allow-list, signature stripping deleted (`2752d08`, `4d67ceb`) |

### (i) Measured economics

Per-route owner-finding numbers: `docs/spikes/owner_routes.md`. Budget table (200 owners a week: about $124-190 a month, or about $104 while Gemini is free; about 70-130 owners a week fit the budget once the credit ends): design doc section 12. Its third-party prices and the 15% yield are unconfirmed.

### (j) Known risks

- Heartbeat lease (migration 0009) replaced the 60-minute stale rule: a job with no heartbeat for 5 minutes is requeued, so the one-worker caveat is gone.
- Restarting the worker (`deploy.sh`) while a job runs marks it `cancelled`, not requeued: deploy only when the queue is idle.
- The VM runs Python 3.14.10 (pinned by `UV_PYTHON=3.14` in `deploy/deploy.sh`), like the Mac. Changing the VM's Python needs `/opt/gtm/.venv` emptied by hand first as `gtm` (root-owned parent, uv cannot remove it).
- A wrongly suppressed lead (including a wrong `not-interested`) can only be fixed in the database.
- The `weekly_target=200` row in `settings` equals the default (f7).
- Plan 3a: full suite was 573 passed, 1 failed before the review fixes (`tests/test_jobs.py::test_enqueue_then_claim_returns_the_job_running`; passes alone 3 of 3; probable cause the live VM worker claiming the test job between enqueue and claim, **unverified**); not re-run after the fixes. Review fixes: suburb time zones, leads stranded uncleaned after a mid-tile budget block, tiles left running after a block, tests polluting `cost_log`, `test_schedule` jobs a live worker could claim (now `run_after` +10 years), `InvalidURL` crash in `fetch_page`.
- Gmail send (including from the VM), thread/bounce reading and a heavy unattended pass (enrich, signals) on the worker are unproven live (only a no-op `clean` has run).
- Deferred minors, accepted: `setting("typo")` raises a bare KeyError; unused `now` parameter in `credit_remaining_usd`; paid-mode check ignores the pending amount (can overshoot a cap by one call); `require` is check-then-act with no reservation; `llm.py` reads prices after the paid Gemini call (a failed read drops the cost row); `researcher.py` param `budget=150` shadows the module; the settings page keeps its own copy of the default values (`web/lib/settings.ts`); `verify.mts` leaves a queued `clean` TEST job and `q.length === 1` is brittle; worker: an exception in `finish` kills the loop, `enqueue` does not reject unknown kinds, no test for `cmd_enqueue` `--` stripping; `tests/test_worker.py` lacks `pytestmark db`; no boundary tests for budget.

### (k) Working agreements with the owner

Concise answers; no assumptions; verify before claiming; one question at a time when brainstorming; confirm any cost before spending; never print keys. Parallel agents for independent work. Ponytail together with superpowers for coding. **The owner dislikes over-engineering and rabbit holes (the signature-stripping detour): prefer deleting code to patching it.** Keep the graphify graph updated (`graphify-out/` is git-ignored). One pytest process at a time against the real Supabase project (`mkdir /tmp/gtm-pytest.lock`).

### (l) First steps for the next session, in order

1. Merge the Plan 2 PR if still open, and the Plan 3a PR once the coordinator opens it. Read `docs/runbooks/cloud-runner.md` open items.
2. First real small send of the 8 selected Houston leads: still NOT done. Needs owner approval of each paid or send step: Review-page approval, `draft`, reading every draft in Gmail, `send` dry run, then `send --confirm` small.
3. Then Plan 3b (Scrape & Coverage and Batches pages), or turn on the daily walk schedule.

The graphify graph was refreshed 2026-11-12 with deep doc extraction (`graphify-out/`, git-ignored); `/graphify . --update` only after further changes.

## 1. What this is and where things stand

A personal "GTM OS" for med spa cold email, for one operator: Soban (KodoAI founder, soban@kodoai.xyz). Pipeline: scrape US med spas from Google Maps (Apify) > clean (plain rules) > enrich to a named decision-maker with a verified email (finders `site`, `search`, `research`, `prospeo`; Hunter Email Finder verifies; see section 5a) > judge buying signals from the lead's own website (Gemini primary, Groq fallback) > auto-select > operator approves in the UI > draft in Gmail (Touch 1 under mechanical checks, Touch 2/3 templates) > explicit send with caps > read replies/bounces > per-batch metrics. Local Next.js UI. Supabase Postgres is the only database. The old Pakistan scraper is deleted (in git history before commit 8518f81). Spec: `docs/superpowers/specs/2026-11-09-kodoai-gtm-os-design.md`; plan: `docs/superpowers/plans/2026-11-09-kodoai-gtm-os.md` (19 tasks, all complete).

| Box | Items |
|---|---|
| **Built** | (+ Plan 1 foundation and the local reply classifier, see section 0) All 19 plan tasks: scrape, clean, enrich, signals, select, draft, follow-ups, send, replies, mailboxes, Notion history import, web UI (Leads, Review, Outreach, Dashboard, Login), `batch_metrics` view, 6 migrations, final Opus code review with fixes |
| **Verified live** | Supabase project `alvxsbnfthvaiquhytig`, migrations 0001-0009 applied (0007-0009 added 2026-11-12). RLS restricts every table to operator soban@kodoai.xyz (proved with a throwaway non-operator user: reads 0 rows, cannot write). Gmail OAuth (Desktop client, Internal; scopes `gmail.compose` + `gmail.readonly`) and a test draft created in Drafts. Apify actor `compass~crawler-google-places` (price measured). Hunter free keys (credit behaviour measured). Groq `openai/gpt-oss-120b` reliable. Serper works (key replaced and re-tested 2026-11-10; session fact). Vertex Gemini `gemini-3.5-flash` is the primary LLM and ran the Houston batch (2026-11-11). Operator mailbox row registered (cap 40, enabled 2026-11-10). Suppression holds 434 imported rows |
| **Not yet verified live** | Gmail `send_draft`; reading threads and bounces (`thread_messages`, `recent_bounces`); Touch 2/3 threading with In-Reply-To headers; a heavy pass (enrich, signals) on the VM (only `clean` and one `walk` tile have run there); deeper walk caps; sub-tiling saturated tiles; the walk on the daily schedule unattended; Vertex fallback behavior when the credit ends. No real end-to-end batch has run. Prospeo and other finders were measured on saved names (section 7, `docs/spikes/owner_routes.md`). The suite is 509 tests, ~5-6 min, hits the real Supabase project (coordinator's count 2026-11-12; not re-run for this doc) |
| **Blocked / waiting** | Nothing technically blocked. Waiting on owner: Hunter plan decision; first real send; whether to turn on the daily walk schedule; no paid Apify top-up without asking (free credit ends 2026-11-24). Done: Notion Batch03 re-pulled 2026-11-10 (32 rows, nothing new); Supabase signups disabled by owner 2026-11-10 |

Funnel reality (Houston, small samples): clean keeps ~63-87% (87% on the 2026-11-11 batch, 52 of 60); names are found for ~62% of cleaned leads but most fail at name > verified email, so enriched is ~17% (9 of 52, 2026-11-11 batch, after the `ovme.com` chain was dropped); website-only evidence gave 0 of 6 dated signals, so most leads will be **relevance-led with thin personalisation**. Target 100-200 emailable leads a week needs on the order of 1,000+ scraped places a week at ~15-20% yield (unverified projection) and Hunter/Prospeo credits are the real limit (section 7).

**End to end as it stands (2026-11-11):** scrape (Apify) > clean (rules) > enrich (`site,search,research,prospeo`, first verified buyer wins) > signals (Gemini primary) > select > operator approves in the UI > draft (Gmail) > `send --confirm` > replies. Send stays a separate explicit step. Owner-finding detail and measurements: section 5a and `docs/spikes/owner_routes.md`.

## 2. First 10 minutes

Prerequisites: macOS, `uv` (Python; pyproject says `>=3.12`, venv resolved to 3.14), Node + npm, a populated `.env` at the repo root (git-ignored; do NOT print or read values), `web/.env.local` (git-ignored; holds `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`), and `.secrets/` (git-ignored; holds `google_oauth_client.json` and the Gmail token for the operator mailbox).

```
cd "/Users/sobanahmad/Work/KodoAI/Sales & Outreach/KodoAI-GTM-OS"
uv sync
uv run pytest -q                     # ~5-6 min, HITS THE REAL SUPABASE PROJECT. One pytest process at a time
cd web && npm install && npm run dev # UI on http://localhost:3000; login = emailed magic link to the operator address
cd web && npx tsc --noEmit           # typecheck
cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts        # UI write actions under RLS (seeds then deletes TEST rows)
cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/rls_intruder.mts  # non-operator sees/changes nothing
uv run python -m gtm.cli --help      # every pass
```

Env variable NAMES (values never in docs): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` (script-side only), `APIFY_API_KEY` (+`_2`..`_9`), `HUNTER_API_KEY` (+`_2`..`_9`), `GROQ_API_KEY`, `GEMINI_AGENT_PLATFORM_API_KEY`, `PROSPEO_API_KEY`, `HARVEST_API_KEY`, `SERP_API_KEY` (+ `SERP_PROVIDER=serper`); the old `GEMINI_API_KEY` setting is gone (an AI Studio key `GEMINI_STUDIO_API_KEY` may sit in `.env`; unused, its prepaid credit is depleted), `GOOGLE_OAUTH_CLIENT_FILE`, `DAILY_CAP`, `RAMP_START`, `RAMP_STEP`, `PAUSE_BOUNCE_RATE`, `PAUSE_MIN_SENDS`, `SIGNAL_MAX_AGE_DAYS`, `POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE`. Only `gtm/config.py` reads the environment. Settings defaults in code: cap 40, ramp 10/+5, pause 3% over 20 sends, signal age 0 (= refuse to run). The real `.env` overrides them (RAMP_START=20, RAMP_STEP=5, DAILY_CAP=40, PAUSE_BOUNCE_RATE=0.05, PAUSE_MIN_SENDS=40, SIGNAL_MAX_AGE_DAYS=90, per the brief and `docs/spikes/sending_history.md`; values not re-read here).

## 3. Architecture and file map

All Python is run as `uv run python -m gtm.cli <pass>` from the repo root. Lead identity = Google place ID, globally unique. LLM only judges/phrases; rules and code gate.

| File | Role |
|---|---|
| `gtm/config.py` | `Settings`, the only environment reader; numbered key lists |
| `gtm/db.py` | `get_db()` (secret key client), `fetch_all(build)` pages past the 1000-row API cap |
| `gtm/status.py` | `Status` enum (14 values) |
| `gtm/costs.py` | `log_cost(provider, units, usd, batch_id, lead_id, note)` into `cost_log` |
| `gtm/apify.py` | Actor run with hard `maxTotalChargeUsd` (min 0.50), picks key with most remaining budget |
| `gtm/scrape.py` | `new_batch`, `scrape_input`, `place_to_lead`, `scrape_city` (insert-new-only; default queries "med spa","aesthetics clinic","botox" with website filter) |
| `gtm/clean.py` | `clean_decision` + `run_clean`: closed, no_website (booking/social platform domains, plus tenant suffixes like `*.as.me`, `*.acuityscheduling.com`, `*.squareup.com`), not_us, `not_a_clinic` (academy/school/training/university/college in name or categories; a real med spa named "Academy" is a known miss), category, day_spa, chain (chains.txt or brand repeated >=3 in batch), duplicate_domain (most reviews wins). `chains.txt` now has `ovme` (uncommitted edit seen 2026-11-11); it matches lead names, not domains |
| `gtm/buyer.py` | `is_role_email`, `is_decision_maker` (MedSpa section 3), `pick_buyer` (verification `valid` AND score >= 80, role addresses never) |
| `gtm/hunter.py` | `HunterPool`: Domain Search, Email Finder, key rotation, `OutOfCredits` |
| `gtm/sitescrape.py` | Free owner-name scrape of About/Team/Contact pages + JSON-LD; `http_fetch` |
| `gtm/search.py` | `serper_search` |
| `gtm/owner_search.py` | "owner of <domain>" search, Groq reads results, `validate_owner` code guard, then Hunter Email Finder |
| `gtm/enrich.py` | `site` and `hunter` finders, `run_enrich`: tries finders in order, stops at first verified buyer. A failed lead stays `no_buyer` but keeps its best named decision-maker (`owner_name/title/email`, `email_verified=false`); retries reuse it. Out of credits leaves leads `cleaned` |
| `gtm/researcher.py` | `research` finder: Gemini function-calling loop (web_search via Serper, fetch_page), then `validate` code guard, then Hunter Email Finder |
| `gtm/prospeo.py` | `prospeo` finder: Enrich Person by name + company website, verified emails only |
| `gtm/harvest.py` | `harvest` finder (opt-in): HarvestAPI LinkedIn profile lookup, USD budget cap |
| `gtm/llm.py` | `complete_json`: Vertex Gemini `gemini-3.5-flash` primary (retries 429/503), Groq `gpt-oss-120b` fallback (token-per-minute `Throttle`) |
| `gtm/signals.py` | `fetch_evidence` (13 site paths, booking platform detection), `validate_signal`, `judge_to_signal`, `run_signals` |
| `gtm/select.py` | `select_decision`, `blocked_reason`, `_blocklists`, `run_select` (model writes only the one-line reason, with a code fallback) |
| `gtm/mailboxes.py` | `assign_mailbox` (sticky, least-loaded, optional restriction) |
| `gtm/draft.py` | `check_draft` (mechanical writing rules), `draft_touch1`, `build_followup`, `footer`, `run_draft` (needs `approved=true`), `run_followups` |
| `gtm/gmail.py` | OAuth, `create_draft`, `send_draft`, `parse_message`, `thread_messages`, `recent_bounces` |
| `gtm/send.py` | `allowance`, `should_pause`, `send_due`, `send_with_reply_check` (the ONLY place a draft becomes an email) |
| `gtm/replies.py` | `classify_reply` (rules first: bounce, auto-reply, opt-out; then `local_kind`: bare-decline allow-list `NEG_FULL` and positive cues; the model decides the rest), `apply_reply` (negative: suppression reason `not-interested`), `run_replies` |
| `gtm/import_history.py` | Notion history lines into `suppression` (idempotent) |
| `gtm/cli.py` | argparse entry point (`build_parser()`), one subcommand per pass, plus `worker` and `enqueue` |
| `gtm/settings_store.py` | `setting(key)` / `set_setting` over the `settings` table, `DEFAULTS`, 60 s cache |
| `gtm/budget.py` | Daily provider caps and the paid-Gemini gate; `BudgetExceeded` (the worker maps it to `paused_budget`) |
| `gtm/jobs.py` | `enqueue`, `claim` (atomic `claim_job` RPC), `finish` (only ends `running` jobs), `requeue_stale` (fails a job after 3 attempts) over the `jobs` table |
| `gtm/worker.py` | `gtm worker`: polls `jobs`, runs allowed passes (not `send`) through the CLI parser with stdout captured as the result |
| `gtm/data/` | `draft_prompt.md` (Touch 1 system prompt), `signal_prompt.md` (condensed MedSpa Touch-1 sections 4-5; a test pins the vector names), `chains.txt` |
| `deploy/` | VM bootstrap, `deploy.sh` (git archive over `gcloud compute ssh`), `fetch_secrets.py`, systemd unit, DB latency script; see `docs/runbooks/cloud-runner.md` |
| `supabase/migrations/0001_init.sql` | 6 tables, RLS on |
| `0002` | `leads.categories text[]`, `leads.closed` |
| `0003` | `leads.select_reason` |
| `0004` | `touches.subject/body/objective` |
| `0005_rls_single_operator.sql` | policy `operator_only` per table: JWT email must equal soban@kodoai.xyz (edit it in every policy to change operator) |
| `0006_batch_metrics_view.sql` | `batch_metrics` view, `security_invoker=true` |
| `0007_jobs_settings.sql` | `settings` and `jobs` tables, `claim_job`, `spend_summary` view |
| `0008_claim_job_search_path.sql` | `claim_job` gets a fixed `search_path` |
| `0009_job_heartbeat.sql` | `jobs.heartbeat_at`; `claim_job` sets it |
| `web/app/{page,layout,globals.css}` | Shell |
| `web/app/login/page.tsx` | Email-link login (shouldCreateUser false), optional password |
| `web/app/leads/page.tsx` | Filters (status, batch, city, state, vector, has email), sort, row detail with evidence |
| `web/app/review/page.tsx` | `selected` leads with reason + evidence; bulk approve/reject, per-lead override |
| `web/app/outreach/page.tsx` | Drafts, sequence tracker, mailbox pause clear, reply outcome marking, mark booked. No send button, no draft editing |
| `web/app/dashboard/page.tsx` | Per-batch funnel and spend from `batch_metrics` |
| `web/app/settings/page.tsx` | Owner settings (budget, Google credit, Allow paid Gemini, API prices, daily caps), spend meter from `spend_summary`, last 50 jobs with enqueue, cancel (queued) and retry (failed or paused_budget). `web/lib/settings.ts` mirrors `DEFAULTS` in `gtm/settings_store.py` |
| `web/components/Evidence.tsx` | Quote + summary + source link display |
| `web/lib/args.ts` | `splitArgs`: shell-style splitting so quoted job args (`--query "med spa"`) work |
| `web/lib/{supabase,actions,fetchAll,types,useRequireSession,settings}.ts` | Browser client (publishable key + operator session), the write actions, paging, types, session guard |
| `web/scripts/verify.mts`, `rls_intruder.mts` | Live verification scripts (use the secret key from `../.env`; never bundled) |
| `scripts/*.py` | One-off spikes and measurement scripts (spike_apify*, spike_hunter*, spike_llm, measure_*, capture_owner_names). Not part of the app |
| `tests/` | `test_clean, config, costs, draft, enrich, gmail, harvest, hunter, import_history, llm, metrics, packaging, paging, prospeo, replies, researcher, scrape, search, search_owner, select, send, signals, sitescrape` plus Plan 1 files `test_budget, cli, jobs, settings_store, worker`, with `support.py` and `conftest.py` (509 tests total, 2026-11-12) |
| `MedSpa/` | Owner's outreach rules (section 11) |
| `docs/spikes/` | Measurements (section 7) |
| `docs/handoffs/` | **STALE**: three handoffs from the deleted Pakistan scraper era (Houston/Hunter keys/ICP). Not about this OS; historical only |

## 4. Data model and lead statuses

Tables (all RLS operator-only): `batches` (one per scrape: city, state, query), `leads`, `touches`, `mailboxes`, `suppression`, `cost_log`; view `batch_metrics`.

- `leads`: place_id (unique), name, website, domain, address, city, state, category, categories[], closed, rating, review_count, owner_name/title/email, email_source, email_verified, signal jsonb, vector (`conversion_recovery`|`capacity`|`rebooking_retention`), signal_led, approved (default false), status, reject_reason, select_reason, mailbox_id (sticky), batch_id.
- `touches`: lead_id, touch_no (1,2,3), status (`drafted`|`sent`|`cancelled`), gmail_draft_id, gmail_thread_id, scheduled_for, sent_at, outcome, subject, body, objective. Unique (lead_id, touch_no).
- `suppression`: email and/or domain, reason (`notion-contacted`, `notion-bounce`, `do-not-contact`, `not-interested`, `opt-out reply`, `bounce`). One entry blocks the whole company.
- `mailboxes`: address, daily_cap, enabled_on, paused, paused_reason.
- `cost_log`: provider (`apify`, `hunter`, `serper`, `groq`...), units, usd, batch_id, lead_id, note.

Status flow: `scraped` > `cleaned` | `rejected` > `enriched` | `no_buyer` > `signalled` > `selected` (+ `approved=true` by operator) > `drafted` > `sent` > `replied` > `booked`. Side states `bounced`, `suppressed`, `unsubscribed`. Notes: a signalled lead failing a non-suppression rule stays `signalled` with `reject_reason`; a suppressed lead becomes `suppressed`. Reply/bounce/opt-out removes the lead from `sent`, which stops later touches. Cadence Day 0/3/7, no Touch 4.

## 5. How each pass is run

All via `uv run python -m gtm.cli ...`. "Batch" = batch UUID printed by `scrape`.

Jobs: `enqueue <kind> -- <pass flags>` queues a pass (the Settings jobs panel does the same); `worker [--poll 15]` runs queued jobs (everything except `send`). Several workers are safe since migration 0009 (heartbeat lease); in practice one runs on the VM. A capped enrich job ends `paused_budget`; Ctrl-C marks a job `cancelled`.

| Command | Flags | Cost / effect |
|---|---|---|
| `scrape` | `--city --state` (req), `--query` (repeatable), `--max-places 40` (per query), `--max-usd 0.50` | **Spends Apify credit** (~$0.005/place incl. website filter; hard cap per run). Creates a batch, inserts new leads as `scraped`, never touches known place IDs |
| `clean` | `--batch` | Free. Rule-based |
| `enrich` | `--batch`, `--limit N`, `--finders` (default `site,search,research,prospeo`), `--harvest-budget` USD (1.0), `--research-budget` searches per run (150), `--retry-no-buyer` | Spends **Hunter credits**, **Prospeo credits**, **Serper queries**, **Gemini tokens**. Use `--limit` first. Stops on out-of-credits. `--retry-no-buyer` re-runs `no_buyer` leads and spends credits again. See 5a |
| `signals` | `--batch`, `--max-age-days` | Gemini tokens (Groq fallback); refuses if recency window unset (`SIGNAL_MAX_AGE_DAYS`) |
| `select` | `--batch` | LLM (Gemini primary; one short sentence per selected lead). Free of paid APIs otherwise |
| (UI) Review page | approve/reject | Sets `approved`; nothing else |
| `draft` | `--batch`, `--mailbox ADDR` (repeatable) | Creates **Gmail drafts** for `selected` AND `approved` leads. Nothing sent. LLM tokens |
| `followups` | none | Reads replies first, then drafts due Touch 2/3 in Gmail. Nothing sent |
| `send` | `--confirm` | Without `--confirm`: dry run printing each mailbox's allowance. With it: reads replies/bounces, then **sends due drafts** within allowance, pausing on bounce spike |
| `replies` | none | Reads Gmail (read-only), classifies (rules, then local bare-decline/positive cues, then the model), sets statuses, writes opt-outs and bare-decline `not-interested` replies to `suppression`. Positives are only flagged |
| `mailbox add` / `mailbox unpause` | `--address` (req), `--cap`, `--enabled-on YYYY-MM-DD` | DB only. A new mailbox needs its own warm-up and DNS check first |
| `import-history FILE` | lines `email\|website\|status\|reply type\|DNC` | DB only; idempotent; Notion columns Email, Website, Status, Reply Type, Do Not Contact |

### 5a. Enrich in detail (as of 2026-11-11)

- **Buyer rule:** named decision-maker (founder/owner/CEO/president/COO/executive director; MedSpa section 3) plus an email with verification `valid` AND score >= 80. Owner ruling 2026-11-10: personal or business email both fine if verified; `accept_all` stays out. A role address never qualifies.
- **Finders, in order, stop at first verified buyer:** `site` (free site scrape for a name, then Hunter Email Finder), `search` ("owner of <domain>" Serper search, LLM reads results, code guard, then Email Finder), `research` (Gemini loop with web_search + fetch_page; max 6 turns, 8 searches, 10 fetches per lead; runs only for leads with no named owner; then Email Finder), `prospeo` (Enrich Person for each named owner, `only_verified_email`; 1 credit only on a find; calls spaced 2 s, 429 retried; VERIFIED counts as score 100 because Prospeo gives no score).
- **Opt-in via `--finders`:** `hunter` (Domain Search; Houston run: 33 credits for 1 enriched lead) and `harvest` (HarvestAPI LinkedIn; no emails found in ~22 lookups, ~$0.004/profile). Email Finder inside site/search spent 19 credits for 4 enriched.
- **`research` code guard:** the name must appear verbatim in fetched text or a search snippet, the text must be about THIS business, a decision-maker title or "founded by" must be near the name, first AND last name required, directory/list pages rejected, Medical Director / Managing Member / Partner alone rejected. Wrong-attribution lesson: it once put the owner of a different clinic on Miliv Med Spa; the owner confirmed the correct names for that and one other lead by hand.
- **Saved names:** a failed lead keeps its best named decision-maker (status stays `no_buyer`, `email_verified=false`), and retries or later finders reuse it. A retry never erases a saved email (bug fixed 2026-11-10).

**Recommended order for the first small batch** (owner approves each paid/send step):
1. Re-pull Notion Batch03 (all five columns) and `import-history` before every new batch (last done 2026-11-10: 32 rows, nothing new). Check suppression count grew sensibly.
2. `scrape --city <one> --state <ST> --max-places 20` (about 3 queries x 20 places, roughly $0.30 to $0.50, under free credit). Note the batch id.
3. `clean --batch ID`. Inspect counts.
4. `enrich --batch ID --limit 20` (watch Hunter and Prospeo credits; free keys only).
5. `signals --batch ID`, then `select --batch ID`.
6. UI Review page: approve a handful (5 to 10) after reading evidence.
7. `draft --batch ID --mailbox soban@kodoai.xyz`; **read every draft in Gmail Drafts** (the Gmail draft is what sends; edit there: true until Plan 4 stores drafts in the database).
8. `send` (dry run), then `send --confirm` for a very small first send. Then `replies` next day, `followups` on Day 3.

## 6. Decisions

### Owner decisions (Soban)
- US only: no Canada, no day spas. Supabase Postgres is the single database (no Google Sheet).
- Decision-maker = founder, owner, CEO or equivalent (MedSpa section 3 also adds COO, executive director, owner medical director). No role addresses (info@ etc.); franchise-local contacts and assistant/former/retired titles excluded.
- Target 200 ready-to-email leads a week. More mailboxes will be added later (multi-mailbox from day one).
- Opt-outs are detected from replies and honoured automatically.
- Footer fields `POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE` are deliberately EMPTY, knowing CAN-SPAM requires all three (FTC guide read 2026-11-09; penalties up to $53,088 per email; not legal advice). The builder must not invent them or block sending on empty.
- Hunter plan decision still pending (2026-11-11); do not buy until the owner decides. Email rule ruling 2026-11-10: verification `valid` AND score >= 80, personal or business email both fine, `accept_all` excluded. No paid Apify top-up without asking (free credit until 2026-11-24).
- Send is always a separate explicit step (`send --confirm`).
- Gate answers (2026-11-10): ramp/cap defaults accepted, later recalibrated from sending history (section 7).

### Assistant rulings (every "Ruling:" line from the ledger, with cost if wrong)
Ledger source: `.superpowers/sdd/2026-11-09-kodoai-gtm-os/progress.md` (git-ignored; copied here). Where the ledger gave no cost, it says "none stated".

| # | Ruling | Cost if wrong |
|---|---|---|
| Setup | Work on branch `gtm-os-build` in place, not a worktree (`.env` is git-ignored; user chose native execution) | None, branch is local |
| Pre-flight | Settings also gets `pause_bounce_rate` (0.03) and `pause_min_sends` (20) because thresholds were to be "in config" | None stated (later recalibrated to 0.05/40 in `.env`) |
| Pre-flight | Add `list_replies(svc, since)` to gmail.py in T15 | None stated (became `thread_messages`/`recent_bounces`) |
| Pre-flight | T13/14/15 take `gmail_for: Callable[[str], Resource]` because there are many mailboxes | None stated |
| T1 | Applied migration via the plugin_supabase MCP to project alvxsbnfthvaiquhytig (verified empty first; same project as SUPABASE_URL) | None, tables new and empty |
| T1 | venv resolved to Python 3.14 though the plan says 3.12; unpinned | Minor version drift |
| T2 | Apify rejects `maxTotalChargeUsd` below $0.50, so tile runs cut from 4 to 2 to stay under the $2 cap | Coverage comparison uses 2 tiles not 4 |
| T7 | Optimised scrape queries (ran A2, $0.6304): on-ICP rule = categories-list-or-name; default queries "med spa","aesthetics clinic","botox" without categoryFilterWords | Query set tuned on one tile of one metro |
| T8 | Added `leads.categories text[]` and `leads.closed` (migration 0002) | Two extra columns |
| T8 | `run_actor(run_input) -> (items, usd)` injected; Apify key picked by most remaining free budget (min cap $0.50) | None |
| T9 | Duplicate-domain winner = place with most reviews (plan said "keep first") | A different sibling location is kept |
| T9 | A lead with no state passes `not_us` (scrape is already countryCode=us) | None stated |
| T9 | Brand repeated >=3 times in a batch is a chain (threshold is a guess; chains.txt seeded with 8 chains) | None stated |
| T9 (correction) | Measured cleaning survival is ~63%, not the 80% first written in funnel.md; fixed there | n/a |
| T10 | Finders take the lead row (domain+name+city), not a bare domain (business-match guard needs the name) | Tests changed |
| T10 | Built `gtm/llm.py` early with Groq `Throttle` (8K tokens/min); T11 reuses it | None (reused) |
| T10 (superseded 2026-11-11) | Default finder order was `site,search,hunter`; now `site,search,research,prospeo`, `hunter` and `harvest` opt-in (measured, section 7) | Credits wasted on Domain Search if re-added |
| T10 | Added `gtm/search.py` (Serper) and `gtm/owner_search.py` after Soban suggested "owner of <domain>" search | None stated |
| T11 | v1 evidence is the lead's own website only (Apify review text is an add-on not scraped); 0/6 dated signals, so mostly relevance-led | Thin personalisation until a social/search source is added |
| T11 | `signal_prompt.md` is a condensed copy of MedSpa Touch-1 sections 4-5 (full 26 KB won't fit Groq's 8K tokens/min); a test pins the three vector names | Drift if the MedSpa file changes |
| T11 | `is_decision_maker` follows MedSpa section 3 (adds COO, executive director; franchise titles hard stop) | A franchise owner with real authority is skipped |
| T11 | MedSpa allows day spas and Canada but Soban's chat instructions exclude both and win by section 1 authority order | None stated |
| T12 | Added `leads.select_reason` (migration 0003) | None stated |
| T12 | A lead failing a non-suppression rule stays `signalled` with `reject_reason` (re-evaluated next run); suppressed leads become `suppressed` | Failed leads re-checked each run (no model calls) |
| T12 | `contacted`/`suppressed` sets hold lowercase emails AND domains so one entry blocks a company (MedSpa: one Touch 1 per company) | None stated |
| T12 | Platform-contradiction screening is not in code; Review page shows detected platform | Operator must eyeball it |
| T13 | Migration 0004 adds `touches.subject/body/objective` | None stated |
| T13 | Touch 2/3 are filled templates, no model; objective is a noun phrase the model writes with Touch 1 | None stated |
| T13 | Touch 1 word count includes greeting and signature (45-70); Touch 2/3 exclude them (10-35, 15-40) | None stated |
| T13 | `run_draft`/`run_followups` take `gmail_for` | None stated |
| T13 | Footer values appended AFTER checks so they never count toward word limits | None stated |
| T13 (limit) | `check_draft` is mechanical only; cannot verify the model's signal/handoff sentence is faithful to evidence, so drafts stay in Gmail for review | Operator must read drafts |
| T14 | Send is dry-run unless `--confirm` | None stated |
| T14 | Complaints are not detectable via Gmail API in v1; pause uses bounce rate only | A spam-complaint pause relies on the operator noticing |
| T14 | Ramp defaults 10/+5/cap 40 per Soban's gate answer (since overridden in `.env`) | None stated |
| T14 | Follow-ups sort before new leads when allowance is short; held (not cancelled) when another lead at the same company was already emailed | None stated |
| T15 | gmail.py gained `parse_message`/`thread_messages`/`recent_bounces`; bounces found by searching mailer-daemon mail | None stated (live behaviour unverified) |
| T15 | `bounce` is a sixth reply kind (apply sets `bounced`) | None stated |
| T15 | Opt-out suppresses the lead's address, the replier's address and the BUSINESS domain, never a free-mail domain | None stated |
| T15 | `new_text()` strips quoted history so our own footer ("stop") cannot cause a false opt-out | None stated; see deferred quote-cut bug |
| T15 (limit) | An auto-reply is re-seen each run; a real reply saying "out of office" is misread as `auto_reply` | Operator should skim replies |
| T16 | Browser-only app (supabase-js + publishable key + operator session), no server components; email-link login, optional password | None stated |
| T16 | RLS verified with a minted one-off session (generate_link + verifyOtp) | None |
| T17 | Write actions live in `web/lib/actions.ts`, verified by `verify.mts` (secret key only in that dev script) | None |
| T18 | Outreach page = read plus 3 DB writes (clear pause, mark outcome, mark booked); no send button, no draft editing (a DB copy of the body would diverge from the Gmail draft; true until Plan 4) | None stated |
| T18 | Sent-today and sequence tracker computed from touches in the browser; ramp allowance not shown (ramp numbers live in Python settings) | None stated |
| T19 | `batch_metrics` reports Hunter in credits, not USD (no plan priced) | A dollar figure appears once a plan is chosen |
| T19 | Funnel columns count leads that reached each stage from surviving data (one status per lead, no stage timestamps); operator-`rejected` counts as past cleaning, rule-`rejected` does not | None stated |
| T19 | View is `security_invoker` so RLS applies; test proves signed-out read returns nothing | None |
| T19 | Deleted four empty "Metrics TX 2026-11-10" batches left by its own failed fixture; fixture now always cleans up | None |
| Final | Fixed gtm/data untracked (stale `data/` gitignore rule hid the prompts and chains; fresh clone failed at import) | Fixed |
| Final | RLS migration 0005 pending Soban's confirmation: only Soban can approve (reviewer graded it Critical before real data). **Resolved 2026-11-10**: applied; only `operator_only` policies remain; `rls_intruder.mts` passes | Resolved |
| Import | `assign_mailbox`/`run_draft` take an optional mailbox restriction (`gtm draft --mailbox ADDR`) because the real soban@kodoai.xyz row now exists and tests must not pick it | None stated |
| Final | Fixed test cleanup that deleted production suppression rows (wiped 6 imported rows; also could wipe real opt-outs). Now `tests/support.py purge_test_suppression` deletes only the tests' own addresses; importer reason is `notion-bounce`. 6 rows restored; suppression = 434 after a full reply+send test run | Fixed |

## 7. Measured numbers and settings (sources in `docs/spikes/`)

| Item | Number | Source |
|---|---|---|
| Apify price | $0.004/place; website filter +$0.001; min per-run cap $0.50; run script spend $1.476 of $2 cap | `apify.md` |
| Coverage | One broad search stops at 120; 0 of 73 tile places in the broad 120, so narrow tiles by suburb needed; tiles-per-metro NOT measured | `apify.md` |
| Cleaning survival | ~63% kept (155 of 237 unique places; ~$0.008-0.009 per kept place) | `apify.md`, `funnel.md` |
| Hunter | 1 credit per Domain Search returning results, 0 if empty; Email Finder 1 only if found; 42% domains return any email; 9% (4 of 45) verified decision-maker; 55% of emails had no title | `hunter.md` |
| Owner-name lever | Site scrape 5/45 names (11%); Serper+Groq 24/45 (53%) names; verified emails 4/45 (9%) after Email Finder (7 emails, 3 accept-all) | `owner_lever.md` |
| Plan sizing | Hunter-only at 200/week needs ~2,200 domains, ~930 credits/week (~4,000/month): Growth ($149/mo); Starter ($49/mo, 2,000 credits) covers ~100/week. Apify ~$21/week at that volume. Pricing read 2026-11-10 | `funnel.md`, `hunter.md` |
| Sending capacity | 200 leads/week x 3 touches ~ 600 emails/week ~ 85-120/day, about 3 mailboxes at 40/day | `funnel.md` |
| LLM (current) | Primary: Vertex Gemini `gemini-3.5-flash` (endpoint aiplatform.googleapis.com, billed to the owner's Google Cloud credit). Fallback: Groq `gpt-oss-120b`. `gemini-3.8-flash` also works (similar quality, slower in one run), not used. AI Studio key prepaid credit depleted, unused. Groq Developer tier was unavailable when tried. The two rows below are the older free-tier spike and predate this change | session facts 2026-11-11; `llm.md` is stale on primary/fallback |
| Groq | `openai/gpt-oss-120b` 20/20 valid JSON, ~1 s; limits 30 RPM, 1K RPD, 8K TPM, 200K TPD (free-tier status of these numbers unconfirmed); ~50-60 evidence-heavy leads/day | `llm.md` |
| Gemini (free AI Studio tier, old) | `gemini-3.5-flash` only 10/20 valid (429/503), median 32 s; grounding 429. Superseded by the Vertex key above | `llm.md` |
| Signals | Website-only: 0 of 6 dated current signals; 5 of 6 relevance-led with handoff, all `conversion_recovery` | `signals_dry_run.md` |
| Gmail limits | Workspace paid 2,000/day/user, trial 500/day; plan type of kodoai.xyz unknown (owner to confirm) | `gmail.md` |
| Houston batch e11d97b6 (2026-11-11) | 60 scraped (3 queries x 20, $0.30), 52 cleaned (87%). Names for ~62% of cleaned. Enriched: 5 first run, 8 after saved-name retry + Prospeo, 10 after `research`, 9 after the `ovme.com` chain was rejected by a re-check of the batch against the current clean rules (of 52). Then `signals` (8 relevance_led, 1 no_handoff) and `select` (8 selected, awaiting operator approval in the UI; nothing drafted or sent). Owner-confirmed 2026-11-11: Jamie Marcelle (joinskindeep.com) and Isam Balat (myplazawellness.com) are the right owners but Hunter and Prospeo found no email for them (names kept, status no_buyer); the researcher's Amy Woehrmann for Miliv Med Spa was wrong (she owns Glow Medical Aesthetics) and was cleared. Six Hunter emails were `accept_all` with scores 72-79 (fail both rules); one chain CEO (ovme.com) was `valid` but Domain Search confidence < 80 | session measurement; no spike file for the funnel itself |
| `research` live run | ~100 Serper searches, 169 Gemini calls (~372K tokens), 3 Hunter credits, 10 new names, 2 new verified emails | `owner_routes.md` |
| Owner routes and other finders | Per-route counts, costs and verdicts (NPI, profiles, Apify contacts add-on, Prospeo, Tomba, Lusha, Harvest, others) | `owner_routes.md` |
| Cost | ~$0.0087 per cleaned lead for scrape; Hunter and Prospeo credits are the real limit. Prospeo free credits: 83 left, renew 2026-11-24 | session facts 2026-11-11 |
| Other enrichers (2026-11-10 status check) | Tomba free, 25 searches/5 per day, ends 2026-11-28; Apollo key lacks scope. Later results in `owner_routes.md` | `enrichers.md` |
| Sending history | Batch01-03: 218 Touch 1, 12 bounces (5.5%), 4 negative, 2 out of office, 0 positive; busiest day 20; nothing logged after 2026-10-12 | `sending_history.md` |
| Derived settings | RAMP_START=20, RAMP_STEP=5, DAILY_CAP=40, PAUSE_BOUNCE_RATE=0.05 over >=40 sends (7-day window), SIGNAL_MAX_AGE_DAYS=90. Judgment calls, not provider rules | `sending_history.md` |
| Mailbox | soban@kodoai.xyz warmed with MailReach (18 conversations, ~40-54 warm emails/day, flat); domain ~3 months old (session fact, not in files). Earlier spec text said 15-30/day and 99% inbox | spec section 3 |

Measurement record for the 2026-11-11 owner-finding experiments: `docs/spikes/owner_routes.md`.

## 8. Safety rules and anti-goals

- Never email someone twice, after an opt-out or a bare "not interested" reply, or from a bounced address. Never damage kodoai.xyz reputation. Never spend Hunter credits on leads cleaning should have dropped. No second source of truth (the Notion problem).
- Suppression and "already contacted" are checked before draft, at select, and again at send time. A suppression entry (email or domain) blocks the whole company. Shared platforms (visibook.com etc.) and free-mail domains are never domain-suppressed.
- Send is always explicit: only `gtm send --confirm` (`gtm/send.py`) turns a draft into an email. A test checks sending lives only there (it greps one file only: deferred minor). The UI has no send button.
- Replies are read before every send (`send_with_reply_check`) and before follow-up drafting, so a Day 2 "stop" blocks Day 3.
- Signals need a source URL and a real recent date, and the quote and the date must appear on the fetched page. Never invent one; a lead with none is relevance-led or not selected.
- Footer fields empty by owner choice (section 6). Do not add or "helpfully" fill them.
- Every paid call writes a `cost_log` row. Never print or commit keys. Secret key is script-side only (Python and the two verify scripts), never in the browser or `NEXT_PUBLIC_*`.
- RLS: every table restricted to operator email in policies (migration 0005). The browser uses the publishable key + operator login.
- Never wipe real suppression rows: db tests must clean up only their own rows.

## 9. Open items and next steps (priority order)

| # | Item | Who |
|---|---|---|
| 1 | Re-pull Notion Batch03 in the five-column format and run `import-history` before EACH new batch (done 2026-11-10: 32 rows, nothing new) | Owner supplies lines; assistant runs import |
| 2 | First real send, still not done: small batch, approve a handful, read every draft in Gmail, then `send --confirm` small. Live-verifies `send_draft`, thread and bounce reading, Touch 2/3 threading | Assistant drives; owner approves each paid/send step |
| 3 | Hunter plan decision (pending). Prospeo free credits renew 2026-11-24 (83 left); Apify free credit ends 2026-11-24 | Owner decides |
| 4 | Chains: `ovme` added to `chains.txt` (matches by name); check other multi-location groups with the same pattern when they appear | Assistant |
| 5 | Name > email is the bottleneck (accept_all, score < 80): decide whether to accept `accept_all` with a lower bar or buy more verification credits | Owner decides |
| 6 | Confirm Workspace plan (paid vs trial) for kodoai.xyz send limits | Owner |
| 7 | Add mailboxes (each needs warm-up and DNS check) for 200/week | Owner |
| 8 | Richer signal sources (Instagram/Facebook posts, Google Business updates, job boards, news; not measured) | Owner decides; assistant measures |
| 9 | Deferred Minor review findings (below; Plan 1 minors are in section 0 (j)) | Assistant, when relevant |
| 10 | Stale docs: bannered 2026-11-12 (`docs/handoffs/*`, `docs/spikes/llm.md`, `docs/spikes/funnel.md`); do not use them as current | Done |
| 11 | **Parked:** finalise the email drafting instructions and the angle strategy once the Batch03 strategy is settled: see `docs/NEXT-email-strategy.md` | Owner + assistant |
| 12 | Plans 1 and 2 are built; Plans 3-6 next (roadmap): see section 0 (d), (e), (l) | Owner, then assistant |
| Done | Supabase signups disabled (owner, 2026-11-10); `.env.example` updated (Serper, Gemini, Prospeo, Harvest names); CLAUDE.md pass list updated | |

**Minor (deferred), copied from the ledger:** clean.py `seen` excludes operator-rejected domains; same owner_email across different domains in one run; bounce substring match (ajo@ vs jo@); quote-cut regex can cut an opt-out that starts "On..."; HTML-only replies collapse to one line so quoted history is not stripped; bare "Stop." with no object goes to the model; `sent_at` uses local date with UTC time and Outreach page uses UTC date; Touch 3 can follow Touch 2 by a day after deferral; leads with no reachable pages are never re-judged; `reason_to_respond` shown unlabeled; groq/serper costs have no batch_id so those dashboard columns are 0; Serper out of credits stops the whole enrich run; `test_sending_lives_only_in_send_py` greps one file only.

## 10. Known gotchas and traps

- Worker leases: migration 0009 heartbeat replaced the 60-minute stale rule, so a second worker no longer re-runs a live job. A restart (`deploy.sh`, `systemctl stop`) cancels a running job: deploy only when the queue is idle (section 0 (j)).
- The suite is 509 tests now (earlier figures of 348 and 389 are stale).
- DB tests (`-m db`, most of them) hit the **real** Supabase project. One pytest process at a time. They must delete only their own rows (`tests/support.py purge_test_suppression`); an earlier cleanup keyed on reason alone deleted real suppression rows.
- Supabase MCP destructive SQL asks for a confirmation that expires after 2 minutes; the user must approve promptly (the 0005 migration expired twice). Two Supabase MCP servers exist (`mcp__supabase__` needed re-auth; `mcp__plugin_supabase_supabase__` worked).
- PostgREST bulk inserts need identical keys on every row. The API caps reads at 1000 rows: always use `gtm.db.fetch_all`.
- macOS `sed -i ''`. The harness once blocked an oddly quoted multi-line shell command as a possible `rm`; keep shell commands simple.
- `.gitignore` contains a catch-all `.*` and `*.csv`: new dotfiles are ignored unless tracked (`.env.example` is tracked). An earlier stale `data/` rule hid `gtm/data/`; `tests/test_packaging.py` guards that.
- Groq's 8K tokens/min is its real throttle (now the fallback only); the free AI Studio Gemini tier was flaky; do not feed the full MedSpa Touch-1 prompt (26 KB) to the model.
- Check `.env` for stale leftovers from the old project (POSTGRES_*, REDIS_*, PROXY_*, META_*, BROWSER_WORKERS, CACHE_TTL_*, etc.): `config.py` ignores them. Many provider keys (Apollo, Snov, Lusha, ContactOut, RocketReach, Tomba) are in `.env` but unused by code; Prospeo and Harvest are now used.
- Draft requires `selected` AND `approved=true` (set on the Review page); selecting alone drafts nothing.
- Follow-ups are held (not cancelled) if another lead at the same company was already emailed.
- Notion history is a snapshot; the OS cannot see anything sent from Notion until re-imported. Batch03 is still running there.
- `uv run` must be executed from the repo root here (pyproject is at root). The root `CLAUDE.md` is the short OS version; the old Pakistan-scraper CLAUDE.md is gone.
- Postal address, ad-disclosure and opt-out line are blank on purpose; do not "fix" them.
- The suite is 509 tests and ~5-6 min; it hits the real Supabase project. Do not run it casually.
- A wrong owner name is the main enrich risk: never trust a model-reported name without the code guard, and check a name's company before accepting (LinkedIn name-only matches can be a different person).

## 11. Where the owner's outreach rules live

`MedSpa/` is the source of truth for email content; code never redefines it (it carries condensed or mechanical copies: `gtm/data/signal_prompt.md`, `gtm/data/draft_prompt.md`, `check_draft`). Authority order (ledger): the owner's chat instructions win over `MedSpa/` where they conflict (US only, no day spas).

| File | Governs |
|---|---|
| `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md` | ICP gates, buyers (section 3), signal evidence fields and vectors (sections 4-5), Touch 1 |
| `MedSpa/Med-Spa-Follow-Up-Master-Prompt.md` | Touch 2 and Touch 3 |
| `MedSpa/medspa-three-touch-playbook.md` | Approved sequence logic (signal-led vs relevance-led); live Notion page and master prompts control execution |
| `MedSpa/KodoAI-Cold-Outreach-Writing-Rules.md` | Mechanical writing rules (word counts, banned phrases, no offers in Touch 1); source for `check_draft` |
| `MedSpa/KodoAI-Med-Spa-ChatGPT-Operating-Guide.md` | Map of the above, written for the ChatGPT workflow (Oct 10, 2026) |
| `MedSpa/MedSpa-Project-Memory.md` | Standing decisions of the project |
| Notion tracker | Historic sending log and duplicate/DNC source: https://app.notion.com/p/Med-Spa-Cold-Email-Tracker-462cc5546c5082b3bab2818d126b4029 (databases Batch01, Batch02, Batch03). Still the live log for Batch03 until ~100 unique sends; imported into `suppression` via `import-history` |

Note: MedSpa gives no recency window for a "current" signal; 90 days (`SIGNAL_MAX_AGE_DAYS`) is the assistant's proposal that the owner set in `.env` (confirmation of owner approval is not recorded in the files: unverified).

Owner working style: concise answers, no assumptions, no hallucination, verify before claiming, one question at a time when something is genuinely theirs to decide.
