# KodoAI GTM OS for Med Spas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One operator tool that scrapes US med spas, cleans, enriches to a verified decision-maker email, finds sourced buying signals, auto-selects leads, drafts/sends from Gmail, and shows per-batch metrics in a local UI.

**Architecture:** Python package `gtm` runs each pass as a CLI command and moves a lead through statuses in Supabase Postgres (the only database). A small local Next.js app in `web/` reads and writes the same database. LLM calls (Groq, Gemini) only judge and phrase; rules and code gate.

**Tech Stack:** Python 3.12 with uv, pytest, supabase-py, apify-client, httpx, google-api-python-client; Next.js + TypeScript + @supabase/supabase-js; Supabase Postgres with RLS. Pin exact versions when adding dependencies (any version known before this plan is old enough).

**Spec:** `docs/superpowers/specs/2026-11-09-kodoai-gtm-os-design.md`. Read it and `MedSpa/` (ICP gates, five evidence fields, vectors, Day 0/3/7, writing rules) before starting. `MedSpa/` is the source of truth for outreach content; do not redefine it.

## Global Constraints

- Statuses, in order: `scraped`, `cleaned` (or `rejected`), `enriched` (or `no_buyer`), `signalled`, `selected`, `drafted`, `sent`, `replied`, `booked`. Side states: `bounced`, `suppressed`, `unsubscribed`.
- US only. No Canada. No day spas. Lead identity is Google place ID, unique globally.
- Store only needed fields. No raw scraper dumps.
- Enriched means a named decision-maker (founder, owner, CEO or equivalent) with a verified email. Role addresses (info@, contact@, hello@) never qualify. Failures are `no_buyer`, kept, never re-bought.
- A signal needs a source URL and a date. Never invent one. No verifiable signal means relevance-led per `MedSpa/`, or not selected.
- Every draft and send checks `suppression` and "already contacted" first. A reply or bounce stops that lead's remaining touches. Cadence is Day 0/3/7, no Touch 4.
- Sending: Gmail API as soban@kodoai.xyz, draft-first, send is a separate explicit action, per-mailbox daily cap and ramp, per-mailbox pause on bounce/complaint spike (operator clears). A lead stays on one mailbox for its sequence. Strict DMARC: Gmail-origin mail only.
- `POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE` are config values, empty by default, appended if set. Never invent them; never block sending on empty.
- Passes run as CLI commands in v1. UI is local, single operator. The Supabase secret key is server/script-side only, never in the browser.
- `config.py` is the only reader of `os.environ`/`.env`. Every paid call writes a `cost_log` row.
- Unverified until measured (spikes): Apify price per place, Hunter credits per search, Groq/Gemini free limits, other enricher plans, Gmail send limits.

## Review Focus

Inputs the spec implies but nobody would think to test, most likely first:
1. Two Maps places with the same website domain (multi-location owner) must yield one emailed lead. Tested in Task 9.
2. Hunter returns only role emails, unverified or accept-all emails, or no title. Expected: `no_buyer`. Tested in Task 10.
3. Titles like "Practice Manager", "Office Manager", "Medical Director" (conservative: not accepted), versus "Founder & CEO", "Owner", "Co-Owner" (accepted). Tested in Task 10.
4. Out-of-office and auto-replies must not count as replies or opt-outs; "please take me off your list" in free text must be an opt-out. Tested in Task 15.
5. An LLM signal with no URL, no date, or older than the allowed age must be dropped, never saved. Tested in Task 11.

---

### Task 1: Scaffold, config, database schema, cost log

**Files:**
- Create: `pyproject.toml`, `gtm/__init__.py`, `gtm/config.py`, `gtm/db.py`, `gtm/status.py`, `gtm/costs.py`, `supabase/migrations/0001_init.sql`, `tests/test_config.py`, `tests/test_costs.py`, `CLAUDE.md` (short: commands, rules above), `.env.example` (replace the old template)

**Interfaces:**
- Produces: `get_settings() -> Settings` (fields: `supabase_url`, `supabase_secret_key`, `apify_keys: list[str]`, `hunter_keys: list[str]`, `groq_api_key`, `gemini_api_key`, `daily_cap: int`, `ramp_start: int`, `ramp_step: int`, `signal_max_age_days: int`, `postal_address`, `ad_disclosure`, `opt_out_line` (last three default `""`)); `get_db() -> supabase.Client`; `class Status(str, Enum)` with the values above; `log_cost(provider: str, units: float, usd: float | None, batch_id: str | None = None, lead_id: str | None = None, note: str = "") -> None`.

- [ ] **Step 1: Commit the baseline.** `git add -A && git commit -m "chore: remove Pakistan scraper, add med spa docs, design and plan"`.
- [ ] **Step 2: Failing tests.** `test_config.py::test_empty_footer_values_default_blank` asserts the three footer fields are `""` with no env set; `test_config.py::test_hunter_keys_collects_numbered_vars` sets `HUNTER_API_KEY` and `HUNTER_API_KEY_2` and asserts both load in order. `test_costs.py::test_log_cost_inserts_row` (marked `db`) writes a row tagged to a test batch and reads it back, then deletes it.
- [ ] **Step 3: Implement** the modules above. Migration `0001_init.sql` creates `batches(id, name, city, state, query, created_at)`, `leads` (place_id unique, name, website, domain, address, city, state, category, rating, review_count, owner_name, owner_title, owner_email, email_source, email_verified, signal jsonb, vector, signal_led bool, approved bool default false, status, reject_reason, mailbox_id, batch_id, timestamps), `mailboxes(id, address, daily_cap, enabled_on, paused, paused_reason)`, `touches(id, lead_id, touch_no, status, gmail_draft_id, gmail_thread_id, scheduled_for, sent_at, outcome)`, `suppression(email, domain, reason, created_at)`, `cost_log(...)`, RLS enabled on all tables with a policy for the single operator user. Apply with the Supabase MCP `apply_migration`.
- [ ] **Step 4: Verify.** `uv run pytest -v` passes; `list_tables` shows all six tables with RLS on.
- [ ] **Step 5: Commit.**

### Task 2: Spike A: one-city Apify run

**Files:** Create `scripts/spike_apify.py`, `docs/spikes/apify.md`

**Interfaces:** Produces measured numbers in `docs/spikes/apify.md`: USD per place, places returned, share with a website, whether the `website` filter works, how `locationQuery` coverage compares with tiled searches, fields available.

- [ ] **Step 1: Ask Soban to confirm city and a hard cost cap (suggest $1) before spending.** Use the Compass Google Maps actor (confirm the actor ID on Apify; do not assume) and set the actor run's maximum-charge option to the cap.
- [ ] **Step 2: Run** one US city, query "med spa", capped. Save the raw items to the scratchpad only, not the repo.
- [ ] **Step 3: Write the findings** to `docs/spikes/apify.md` with the exact numbers and the fields worth keeping; mark anything still unmeasured.
- [ ] **Step 4: Commit.**

### Task 3: Spike B: Hunter

**Files:** Create `scripts/spike_hunter.py`, `docs/spikes/hunter.md`

- [ ] **Step 1: Run** Domain Search on 5 med spa domains from Task 2 using a key with credits (key 1, 3 or 4). Record `X-Credits-Used` / account endpoint deltas per call.
- [ ] **Step 2: Write** to `docs/spikes/hunter.md`: credits per search, what fields come back (position, verification status, confidence, accept-all flag), how many of 5 returned a decision-maker with a verified email, and the paid plan Soban should buy for 200 emailable leads a week.
- [ ] **Step 3: Commit.**

### Task 4: Spike C: LLM limits and grounded search

**Files:** Create `scripts/spike_llm.py`, `docs/spikes/llm.md`

- [ ] **Step 1: Measure** Groq (`openai/gpt-oss-120b`) and Gemini (a Flash model) with 20 small JSON-mode calls each: latency, 429 behaviour, documented free-tier limits (cite the provider docs page), and whether Gemini's Google Search grounding works on the free tier.
- [ ] **Step 2: Write** `docs/spikes/llm.md` and pick the primary and fallback model for judging and phrasing.
- [ ] **Step 3: Commit.**

### Task 5: Spike D: other enrichers

**Files:** Create `docs/spikes/enrichers.md`

- [ ] **Step 1: Call each provider's read-only account/credits endpoint** for Apollo, Snov, Tomba, Prospeo, RocketReach, Lusha, ContactOut and SerpAPI (look up each endpoint in its docs; print no keys). Record plan and remaining credits.
- [ ] **Step 2: Recommend** the one paid fallback after Hunter and the free website-scrape step, with its cost per verified decision-maker email if known. Commit.

### Task 6: Spike E: Gmail API and limits

**Files:** Create `gtm/gmail.py`, `docs/spikes/gmail.md`

**Interfaces:** Produces `gmail_service(mailbox: str) -> Resource` (OAuth token stored under a git-ignored `.secrets/`), `create_draft(svc, to: str, subject: str, body: str) -> str` (draft id), `send_draft(svc, draft_id: str) -> str` (thread id).

- [ ] **Step 1: Walk Soban through** creating a Google Cloud project, enabling the Gmail API and creating OAuth credentials for soban@kodoai.xyz. Add `GOOGLE_OAUTH_CLIENT_FILE` to config.
- [ ] **Step 2: Implement** the interface above; create a draft to Soban's own address and confirm it appears in Drafts.
- [ ] **Step 3: Record** current Workspace daily sending limits from Google's documentation (cite the page) in `docs/spikes/gmail.md`. Commit.

### Task 7: Gate: funnel estimate and decisions

**Files:** Create `docs/spikes/funnel.md`

- [ ] **Step 1: Combine** Tasks 2-6 into a funnel: places scraped to cleaned to buyer found to signal to selected, using measured rates, and the Apify and Hunter spend needed for 200 ready-to-email leads a week.
- [ ] **Step 2: Stop and ask Soban** to approve the Hunter plan, Apify budget, paid fallback and send-cap ramp. No pipeline task starts before this is answered.

### Task 8: Scrape pass

**Files:** Create `gtm/scrape.py`, `tests/test_scrape.py`

**Interfaces:**
- Consumes: `get_db`, `log_cost`, Task 2's measured input shape.
- Produces: `place_to_lead(item: dict, batch_id: str) -> dict`; `scrape_city(db, run_actor, city: str, state: str, queries: list[str], batch_id: str)  # default queries: "med spa", "aesthetics clinic", "botox", with the website filter and no category filter (A2)
   -> tuple[int, int]` returns `(new, already_known)`. `run_actor` is injected so tests use a fake.

- [ ] **Step 1: Failing tests.** `test_place_to_lead_keeps_only_needed_fields` (output keys are exactly the stored lead columns); `test_known_place_id_is_skipped_not_duplicated` (second scrape of the same place returns `(0, 1)` and the row count stays 1); `test_known_place_is_never_requeued_for_enrichment` (its status is unchanged).
- [ ] **Step 2: Implement** with insert-on-conflict-do-nothing on `place_id`; status `scraped`; log Apify cost.
- [ ] **Step 3: Add** CLI `gtm scrape --city --state --query` in `gtm/cli.py`. Run tests, commit.

### Task 9: Clean pass

**Files:** Create `gtm/clean.py`, `tests/test_clean.py`

**Interfaces:** Produces `clean_decision(lead: dict) -> str | None` (reject reason or `None`); `run_clean(db, batch_id: str) -> dict[str, int]` (counts by reason). Reasons: `chain`, `category`, `day_spa`, `closed`, `no_website`, `not_us`, `duplicate_domain`.

- [ ] **Step 1: Failing tests,** one per reason, plus `test_two_places_same_domain_keep_first_reject_second` (Review Focus 1: exactly one survives as `cleaned`, the other is `rejected/duplicate_domain`) and `test_day_spa_is_rejected_but_med_spa_is_kept`.
- [ ] **Step 2: Implement** pure rules. On-ICP means "Medical spa" appears anywhere in the place's `categories` list OR its name matches `med ?spa|medical spa|aesthetic` (measured: the primary `categoryName` alone drops 27 real med spas, `docs/spikes/apify.md` A2). Chain detection uses a small `data/chains.txt` list plus "same name across many places in the batch". Run tests, add CLI `gtm clean`, commit.

### Task 10: Enrich pass

**Files:** Create `gtm/enrich.py`, `gtm/hunter.py`, `gtm/sitescrape.py`, `tests/test_enrich.py`

**Interfaces:**
- Produces: `is_role_email(email: str) -> bool`; `is_decision_maker(title: str | None) -> bool`; `pick_buyer(candidates: list[dict]) -> dict | None` (candidate has `email`, `first_name`, `last_name`, `position`, `verification_status`); `class HunterPool(keys: list[str])` with `domain_search(domain: str) -> list[dict]` (rotates to the next key when one is out of credits, logs cost); `run_enrich(db, finders: list, batch_id: str) -> dict[str, int]` where each finder is `Callable[[str], list[dict]]` tried in order (Hunter, site scrape, then the paid fallback chosen in Task 7).

- [ ] **Step 1: Failing tests.** `test_role_emails_never_qualify` (info@, contact@, hello@, office@, admin@, support@ are role). `test_decision_maker_titles` asserts True for "Founder & CEO", "Owner", "Co-Owner", "Founder", "CEO", "President"; False for "Practice Manager", "Office Manager", "Medical Director", "Aesthetician", `None` (Review Focus 3; "Medical Director" is a conservative call, Soban can allow-list). `test_pick_buyer_requires_verified` (Review Focus 2): only role emails, only unverified or accept-all, or no title all return `None`. `test_failed_lead_is_no_buyer_and_not_rebought` asserts status `no_buyer` and that a second `run_enrich` makes zero finder calls for it. `test_next_finder_runs_only_when_previous_finds_nothing`.
- [ ] **Step 2: Implement** the interface; record `email_source` per lead. Add CLI `gtm enrich`. Run tests, commit.

### Task 11: Signals pass

**Files:** Create `gtm/llm.py`, `gtm/signals.py`, `tests/test_signals.py`

**Interfaces:**
- Produces: `complete_json(system: str, prompt: str) -> dict` (primary and fallback model from Task 4, retries on 429, logs cost); `validate_signal(sig: dict, today: date, max_age_days: int) -> bool`; `run_signals(db, llm, fetch_evidence, batch_id: str) -> dict[str, int]`. `fetch_evidence(lead) -> list[dict]` gathers the lead's website pages and Apify review data (v1 mandatory sources only).

- [ ] **Step 1: Failing tests.** `test_signal_without_url_or_date_is_dropped` and `test_signal_older_than_max_age_is_dropped` (Review Focus 5); `test_lead_with_no_valid_signal_is_relevance_led_not_invented` (signal stays null, `signal_led` false); `test_vector_must_be_one_of_the_three`.
- [ ] **Step 2: Implement.** System prompt is built from `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md` (read it; extract the evidence fields and vector definitions, do not paraphrase them from memory). `signal_max_age_days` default comes from that file; if it states none, ask Soban. Status becomes `signalled`. Add CLI `gtm signals`. Commit.

### Task 12: Select pass

**Files:** Create `gtm/select.py`, `tests/test_select.py`

**Interfaces:** Produces `select_decision(lead: dict, suppressed: set[str], contacted: set[str]) -> tuple[bool, str]` (selected?, reason); `run_select(db, llm, batch_id: str) -> int`.

- [ ] **Step 1: Failing tests:** selected requires `enriched` buyer, email not in suppression or contacted, and a valid signal or relevance-led qualification per `MedSpa/`; each failure returns a specific reason string; a suppressed domain blocks every address on it.
- [ ] **Step 2: Implement.** Mechanical gates in code (read the ICP gates in `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md`; anything fuzzy goes to Soban, not guessed); the LLM only writes the one-line reason. Status `selected`. CLI `gtm select`. Commit.

### Task 13: Mailboxes and draft pass

**Files:** Create `gtm/mailboxes.py`, `gtm/draft.py`, `tests/test_draft.py`

**Interfaces:** Produces `assign_mailbox(db, lead_id: str) -> str` (least-loaded enabled mailbox; sticky once set); `touch_date(first_sent: date, touch_no: int) -> date` (offsets 0, 3, 7; `ValueError` for 4); `check_draft(text: str) -> list[str]` (problems against `MedSpa/KodoAI-Cold-Outreach-Writing-Rules.md`); `footer(settings) -> str` (appends only non-empty configured values); `run_draft(db, llm, gmail, batch_id: str) -> int` (creates Gmail drafts and `touches` rows).

- [ ] **Step 1: Failing tests:** `test_touch_4_is_rejected`; `test_touch_dates_are_day_0_3_7`; `test_footer_is_empty_when_nothing_configured`; `test_footer_appends_only_configured_values`; `test_lead_keeps_same_mailbox_across_touches`; `test_check_draft_flags_each_rule` (build one test per mechanical rule in the writing-rules file).
- [ ] **Step 2: Implement.** The drafting prompt is `MedSpa/Med-Spa-Follow-Up-Master-Prompt.md` and `MedSpa/medspa-three-touch-playbook.md` content; draft pass refuses leads that are suppressed or already contacted. CLI `gtm draft`. Commit.

### Task 14: Send pass

**Files:** Create `gtm/send.py`, `tests/test_send.py`

**Interfaces:** Produces `allowance(mailbox: dict, today: date, ramp_start: int, ramp_step: int, cap: int) -> int` (daily limit: `min(cap, ramp_start + ramp_step * days_since_enabled)`); `should_pause(sent: int, bounced: int, complaints: int) -> bool` (thresholds in config, proposed defaults: bounce rate above 3% of at least 20 sends, or any complaint); `send_due(db, gmail, today: date) -> dict[str, int]`.

- [ ] **Step 1: Failing tests:** `test_allowance_ramps_then_caps`; `test_cap_reached_mid_batch_leaves_rest_drafted`; `test_paused_mailbox_sends_nothing_until_cleared`; `test_suppressed_lead_is_not_sent_even_if_drafted`; `test_reply_or_bounce_cancels_later_touches`; `test_send_requires_explicit_call` (importing or running draft never sends).
- [ ] **Step 2: Implement,** CLI `gtm send --mailbox --limit`. Defaults for `ramp_start`, `ramp_step`, `daily_cap` come from Task 7's decision. Commit.

### Task 15: Reply pass

**Files:** Create `gtm/replies.py`, `tests/test_replies.py`

**Interfaces:** Produces `classify_reply(msg: dict) -> Literal["opt_out","auto_reply","positive","negative","other"]` (`msg` has headers and body text); `apply_reply(db, lead_id: str, kind: str) -> None`; `run_replies(db, gmail, llm) -> dict[str, int]` (polls each mailbox's threads).

- [ ] **Step 1: Failing tests (Review Focus 4):** an `Auto-Submitted: auto-replied` message and "I am out of the office until" are `auto_reply` and change nothing; "please take me off your list", "stop emailing me", "unsubscribe" are `opt_out`; `test_opt_out_suppresses_address_and_domain_and_cancels_touches`; bounce notices set `bounced`.
- [ ] **Step 2: Implement:** rules first, LLM only for positive/negative/other; opt-out writes address and domain to `suppression` the same run. CLI `gtm replies`. Commit.

### Task 16: Web shell, auth, Leads page

**Files:** Create `web/` (Next.js app), `web/lib/supabase.ts`, `web/app/leads/page.tsx`, `web/app/login/page.tsx`

**Interfaces:** Consumes the `leads` table through the publishable key and the operator's Supabase login. Produces a Leads table with filters (status, batch, city, state, vector, has email), sort, and a row-detail panel showing signal evidence with its source link.

- [ ] **Step 1: Scaffold** the app with exact pinned versions; create the operator user in Supabase Auth; confirm an unauthenticated request returns no rows (RLS).
- [ ] **Step 2: Implement** pages. Verify: `npx tsc --noEmit` clean, and the page loads rows locally. Commit.

### Task 17: Review page

**Files:** Create `web/app/review/page.tsx`

- [ ] **Step 1: List `selected` leads** with the LLM reason and evidence link; bulk approve (status stays `selected`, flag `approved`) or reject (status `rejected`, reason "operator"); per-lead override.
- [ ] **Step 2: Verify** with seeded test leads, then delete them. Commit.

### Task 18: Outreach page

**Files:** Create `web/app/outreach/page.tsx`

- [ ] **Step 1: Show** drafts for review/edit, due touches (Day 3/7) per mailbox, each mailbox's allowance used today, pause state with a clear button, and replies with the classified kind.
- [ ] **Step 2: Sending is a button** that calls `gtm send` (or sets `approved_to_send`; builder's choice, documented in `CLAUDE.md`), never automatic. Commit.

### Task 19: Dashboard

**Files:** Create `supabase/migrations/0002_batch_metrics.sql`, `web/app/dashboard/page.tsx`, `tests/test_metrics.py`

**Interfaces:** Produces view `batch_metrics(batch_id, scraped, cleaned, enriched, signalled, drafted, sent, bounced, replied, positive, booked, apify_usd, hunter_usd, usd_per_lead, usd_per_verified_email)`.

- [ ] **Step 1: Failing test** `test_batch_metrics_counts_funnel` (marked `db`): insert a test batch with one lead at each status and cost rows; assert each count and `usd_per_lead`; clean up.
- [ ] **Step 2: Implement** the view and a per-batch table page. Soban marks `positive` and `booked` replies in the UI unless Task 15's classifier is trusted later. Commit.
