# HANDOFF: KodoAI GTM OS (written 2026-11-10, branch `gtm-os-build`, HEAD d876340 when written)

Read this first, then `CLAUDE.md`. Everything here was read from the repo or established in the building session; anything not checked is marked **unverified**.

## 1. What this is and where things stand

A personal "GTM OS" for med spa cold email, for one operator: Soban (KodoAI founder, soban@kodoai.xyz). Pipeline: scrape US med spas from Google Maps (Apify) > clean (plain rules) > enrich to a named decision-maker with a verified email (site scrape, "owner of <domain>" Serper search + Groq, Hunter) > judge buying signals from the lead's own website (Groq) > auto-select > operator approves in the UI > draft in Gmail (Touch 1 under mechanical checks, Touch 2/3 templates) > explicit send with caps > read replies/bounces > per-batch metrics. Local Next.js UI. Supabase Postgres is the only database. The old Pakistan scraper is deleted (in git history before commit 8518f81). Spec: `docs/superpowers/specs/2026-11-09-kodoai-gtm-os-design.md`; plan: `docs/superpowers/plans/2026-11-09-kodoai-gtm-os.md` (19 tasks, all complete).

| Box | Items |
|---|---|
| **Built** | All 19 plan tasks: scrape, clean, enrich, signals, select, draft, follow-ups, send, replies, mailboxes, Notion history import, web UI (Leads, Review, Outreach, Dashboard, Login), `batch_metrics` view, 6 migrations, final Opus code review with fixes |
| **Verified live** | Supabase project `alvxsbnfthvaiquhytig`, all 6 migrations applied. RLS restricts every table to operator soban@kodoai.xyz (proved with a throwaway non-operator user: reads 0 rows, cannot write). Gmail OAuth (Desktop client, Internal; scopes `gmail.compose` + `gmail.readonly`) and a test draft created in Drafts. Apify actor `compass~crawler-google-places` (price measured). Hunter free keys (credit behaviour measured). Groq `openai/gpt-oss-120b` reliable. Serper works (key replaced and re-tested 2026-11-10; session fact). Operator mailbox row registered (cap 40, enabled 2026-11-10). Suppression holds 434 imported rows |
| **Not yet verified live** | Gmail `send_draft`; reading threads and bounces (`thread_messages`, `recent_bounces`); Touch 2/3 threading with In-Reply-To headers. No real end-to-end batch has run. Prospeo (88 free credits) and Tomba (25 searches) finder comparison not done. Nothing else open here: the suite collects 294 tests (2026-11-10, all passing on the last full run) |
| **Blocked / waiting** | Nothing technically blocked. Waiting on owner: re-pull Notion Batch03; Hunter plan decision; disabling Supabase signups; first real small batch; no paid Apify top-up without asking (free credit ends 2026-11-24) |

Funnel reality (Houston, small samples): clean keeps ~63%; Hunter-only gives ~9% verified decision-makers; website-only evidence gave 0 of 6 dated signals, so most leads will be **relevance-led with thin personalisation**. Target 200 ready leads a week is not reachable on current free credits or a single mailbox (see section 7).

## 2. First 10 minutes

Prerequisites: macOS, `uv` (Python; pyproject says `>=3.12`, venv resolved to 3.14), Node + npm, a populated `.env` at the repo root (git-ignored; do NOT print or read values), `web/.env.local` (git-ignored; holds `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`), and `.secrets/` (git-ignored; holds `google_oauth_client.json` and the Gmail token for the operator mailbox).

```
cd "/Users/sobanahmad/Work/KodoAI/Sales & Outreach/KodoAI-GTM-OS"
uv sync
uv run pytest -q                     # ~5 min, HITS THE REAL SUPABASE PROJECT. One pytest process at a time
cd web && npm install && npm run dev # UI on http://localhost:3000; login = emailed magic link to the operator address
cd web && npx tsc --noEmit           # typecheck
cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts        # UI write actions under RLS (seeds then deletes TEST rows)
cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/rls_intruder.mts  # non-operator sees/changes nothing
uv run python -m gtm.cli --help      # every pass
```

Env variable NAMES (values never in docs): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` (script-side only), `APIFY_API_KEY` (+`_2`..`_9`), `HUNTER_API_KEY` (+`_2`..`_9`), `GROQ_API_KEY`, `GEMINI_API_KEY`, `SERP_API_KEY` (+ `SERP_PROVIDER=serper`), `GOOGLE_OAUTH_CLIENT_FILE`, `DAILY_CAP`, `RAMP_START`, `RAMP_STEP`, `PAUSE_BOUNCE_RATE`, `PAUSE_MIN_SENDS`, `SIGNAL_MAX_AGE_DAYS`, `POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE`. Only `gtm/config.py` reads the environment. Settings defaults in code: cap 40, ramp 10/+5, pause 3% over 20 sends, signal age 0 (= refuse to run). The real `.env` overrides them (RAMP_START=20, RAMP_STEP=5, DAILY_CAP=40, PAUSE_BOUNCE_RATE=0.05, PAUSE_MIN_SENDS=40, SIGNAL_MAX_AGE_DAYS=90, per the brief and `docs/spikes/sending_history.md`; values not re-read here).

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
| `gtm/clean.py` | `clean_decision` + `run_clean`: closed, no_website (incl. booking/social platform domains), not_us, category, day_spa, chain (chains.txt or brand repeated >=3 in batch), duplicate_domain (most reviews wins) |
| `gtm/buyer.py` | `is_role_email`, `is_decision_maker` (MedSpa section 3), `pick_buyer` (verified `valid` only, role addresses never) |
| `gtm/hunter.py` | `HunterPool`: Domain Search, Email Finder, key rotation, `OutOfCredits` |
| `gtm/sitescrape.py` | Free owner-name scrape of About/Team/Contact pages + JSON-LD; `http_fetch` |
| `gtm/search.py` | `serper_search` |
| `gtm/owner_search.py` | "owner of <domain>" search, Groq reads results, `validate_owner` code guard, then Hunter Email Finder |
| `gtm/enrich.py` | Finders (`site`, `search`, `hunter`) and `run_enrich`; failures become `no_buyer` (kept, not re-bought); out of credits leaves leads `cleaned` |
| `gtm/llm.py` | `complete_json`: Groq primary (token-per-minute `Throttle`), Gemini fallback |
| `gtm/signals.py` | `fetch_evidence` (13 site paths, booking platform detection), `validate_signal`, `judge_to_signal`, `run_signals` |
| `gtm/select.py` | `select_decision`, `blocked_reason`, `_blocklists`, `run_select` (model writes only the one-line reason, with a code fallback) |
| `gtm/mailboxes.py` | `assign_mailbox` (sticky, least-loaded, optional restriction) |
| `gtm/draft.py` | `check_draft` (mechanical writing rules), `draft_touch1`, `build_followup`, `footer`, `run_draft` (needs `approved=true`), `run_followups` |
| `gtm/gmail.py` | OAuth, `create_draft`, `send_draft`, `parse_message`, `thread_messages`, `recent_bounces` |
| `gtm/send.py` | `allowance`, `should_pause`, `send_due`, `send_with_reply_check` (the ONLY place a draft becomes an email) |
| `gtm/replies.py` | `classify_reply` (rules first; model only splits positive/negative/other), `apply_reply`, `run_replies` |
| `gtm/import_history.py` | Notion history lines into `suppression` (idempotent) |
| `gtm/cli.py` | argparse entry point, one subcommand per pass |
| `gtm/data/` | `draft_prompt.md` (Touch 1 system prompt), `signal_prompt.md` (condensed MedSpa Touch-1 sections 4-5; a test pins the vector names), `chains.txt` |
| `supabase/migrations/0001_init.sql` | 6 tables, RLS on |
| `0002` | `leads.categories text[]`, `leads.closed` |
| `0003` | `leads.select_reason` |
| `0004` | `touches.subject/body/objective` |
| `0005_rls_single_operator.sql` | policy `operator_only` per table: JWT email must equal soban@kodoai.xyz (edit it in every policy to change operator) |
| `0006_batch_metrics_view.sql` | `batch_metrics` view, `security_invoker=true` |
| `web/app/{page,layout,globals.css}` | Shell |
| `web/app/login/page.tsx` | Email-link login (shouldCreateUser false), optional password |
| `web/app/leads/page.tsx` | Filters (status, batch, city, state, vector, has email), sort, row detail with evidence |
| `web/app/review/page.tsx` | `selected` leads with reason + evidence; bulk approve/reject, per-lead override |
| `web/app/outreach/page.tsx` | Drafts, sequence tracker, mailbox pause clear, reply outcome marking, mark booked. No send button, no draft editing |
| `web/app/dashboard/page.tsx` | Per-batch funnel and spend from `batch_metrics` |
| `web/components/Evidence.tsx` | Quote + summary + source link display |
| `web/lib/{supabase,actions,fetchAll,types,useRequireSession}.ts` | Browser client (publishable key + operator session), the write actions, paging, types, session guard |
| `web/scripts/verify.mts`, `rls_intruder.mts` | Live verification scripts (use the secret key from `../.env`; never bundled) |
| `scripts/*.py` | One-off spikes and measurement scripts (spike_apify*, spike_hunter*, spike_llm, measure_*, capture_owner_names). Not part of the app |
| `tests/` | `test_clean, config, costs, draft, enrich, gmail, hunter, import_history, llm, metrics, packaging, paging, replies, scrape, search, search_owner, select, send, signals, sitescrape` + `support.py` (about 181 test functions, more with parametrization) |
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

| Command | Flags | Cost / effect |
|---|---|---|
| `scrape` | `--city --state` (req), `--query` (repeatable), `--max-places 40` (per query), `--max-usd 0.50` | **Spends Apify credit** (~$0.005/place incl. website filter; hard cap per run). Creates a batch, inserts new leads as `scraped`, never touches known place IDs |
| `clean` | `--batch` | Free. Rule-based |
| `enrich` | `--batch`, `--limit N`, `--finders site,search,hunter` | Spends **Hunter credits** (Email Finder/Domain Search), **Serper queries**, **Groq tokens**. Use `--limit` first. Stops on out-of-credits |
| `signals` | `--batch`, `--max-age-days` | Groq tokens; refuses if recency window unset (`SIGNAL_MAX_AGE_DAYS`) |
| `select` | `--batch` | Groq (one short sentence per selected lead). Free of paid APIs otherwise |
| (UI) Review page | approve/reject | Sets `approved`; nothing else |
| `draft` | `--batch`, `--mailbox ADDR` (repeatable) | Creates **Gmail drafts** for `selected` AND `approved` leads. Nothing sent. Groq tokens |
| `followups` | none | Reads replies first, then drafts due Touch 2/3 in Gmail. Nothing sent |
| `send` | `--confirm` | Without `--confirm`: dry run printing each mailbox's allowance. With it: reads replies/bounces, then **sends due drafts** within allowance, pausing on bounce spike |
| `replies` | none | Reads Gmail (read-only), classifies, sets statuses, writes opt-outs to `suppression` |
| `mailbox add` / `mailbox unpause` | `--address` (req), `--cap`, `--enabled-on YYYY-MM-DD` | DB only. A new mailbox needs its own warm-up and DNS check first |
| `import-history FILE` | lines `email\|website\|status\|reply type\|DNC` | DB only; idempotent; Notion columns Email, Website, Status, Reply Type, Do Not Contact |

**Recommended order for the first small batch** (owner approves each paid/send step):
1. Re-pull Notion Batch03 (all five columns) and `import-history`. Check suppression count grew sensibly.
2. `scrape --city <one> --state <ST> --max-places 20` (about 3 queries x 20 places, roughly $0.30 to $0.50, under free credit). Note the batch id.
3. `clean --batch ID`. Inspect counts.
4. `enrich --batch ID --limit 20` (watch Hunter credits; free keys only).
5. `signals --batch ID`, then `select --batch ID`.
6. UI Review page: approve a handful (5 to 10) after reading evidence.
7. `draft --batch ID --mailbox soban@kodoai.xyz`; **read every draft in Gmail Drafts** (the Gmail draft is what sends; edit there).
8. `send` (dry run), then `send --confirm` for a very small first send. Then `replies` next day, `followups` on Day 3.

## 6. Decisions

### Owner decisions (Soban)
- US only: no Canada, no day spas. Supabase Postgres is the single database (no Google Sheet).
- Decision-maker = founder, owner, CEO or equivalent (MedSpa section 3 also adds COO, executive director, owner medical director). No role addresses (info@ etc.); franchise-local contacts and assistant/former/retired titles excluded.
- Target 200 ready-to-email leads a week. More mailboxes will be added later (multi-mailbox from day one).
- Opt-outs are detected from replies and honoured automatically.
- Footer fields `POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE` are deliberately EMPTY, knowing CAN-SPAM requires all three (FTC guide read 2026-11-09; penalties up to $53,088 per email; not legal advice). The builder must not invent them or block sending on empty.
- Do not buy a Hunter plan yet; test free credits and owner-name approach first. No paid Apify top-up without asking (free credit until 2026-11-24).
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
| T10 | Default finder order `site,search,hunter` (cheapest first; union unmeasured) | None stated; reorder after Prospeo/Tomba comparison |
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
| T18 | Outreach page = read plus 3 DB writes (clear pause, mark outcome, mark booked); no send button, no draft editing (a DB copy of the body would diverge from the Gmail draft) | None stated |
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
| Groq | `openai/gpt-oss-120b` 20/20 valid JSON, ~1 s; limits 30 RPM, 1K RPD, 8K TPM, 200K TPD (free-tier status of these numbers unconfirmed); ~50-60 evidence-heavy leads/day | `llm.md` |
| Gemini | `gemini-3.5-flash` only 10/20 valid (429/503), median 32 s; grounding 429. Fallback only | `llm.md` |
| Signals | Website-only: 0 of 6 dated current signals; 5 of 6 relevance-led with handoff, all `conversion_recovery` | `signals_dry_run.md` |
| Gmail limits | Workspace paid 2,000/day/user, trial 500/day; plan type of kodoai.xyz unknown (owner to confirm) | `gmail.md` |
| Other enrichers | Prospeo free, 88 credits, renews 2026-11-24; Tomba free, 25 searches, ends 2026-11-28; Apollo key lacks scope (plan unknown); Lusha/Snov/RocketReach/ContactOut not checked | `enrichers.md` |
| Sending history | Batch01-03: 218 Touch 1, 12 bounces (5.5%), 4 negative, 2 out of office, 0 positive; busiest day 20; nothing logged after 2026-10-12 | `sending_history.md` |
| Derived settings | RAMP_START=20, RAMP_STEP=5, DAILY_CAP=40, PAUSE_BOUNCE_RATE=0.05 over >=40 sends (7-day window), SIGNAL_MAX_AGE_DAYS=90. Judgment calls, not provider rules | `sending_history.md` |
| Mailbox | soban@kodoai.xyz warmed with MailReach (18 conversations, ~40-54 warm emails/day, flat); domain ~3 months old (session fact, not in files). Earlier spec text said 15-30/day and 99% inbox | spec section 3 |

## 8. Safety rules and anti-goals

- Never email someone twice, after an opt-out, or from a bounced address. Never damage kodoai.xyz reputation. Never spend Hunter credits on leads cleaning should have dropped. No second source of truth (the Notion problem).
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
| 1 | Re-pull Notion Batch03 (Med Spa Cold Email Tracker, ~100 unique sends target) in the five-column format and run `import-history` BEFORE the first OS batch | Owner supplies lines; assistant runs import and checks the count |
| 2 | First real small batch: one city, small `--max-places`, small caps, a handful of approved leads, read every draft in Gmail before any send, first `send --confirm` small. This also live-verifies `send_draft`, thread reading, bounce reading and Touch 2/3 In-Reply-To threading | Assistant drives; owner approves each paid/send step |
| 3 | Disable Supabase signups in the dashboard (still open at project level; RLS protects data meanwhile) | Owner |
| 4 | Test Prospeo (88 credits) and Tomba (25 searches) finders on the owner names; decide Hunter plan (do not buy until then). Re-order finders only after a measured union | Assistant measures; owner decides |
| 5 | Optional: Serper-based owner finding at scale (works; key replaced; ~2,500 queries; earlier key ran out and Serper out of credits stops the whole enrich run) | Owner decides budget |
| 6 | Confirm Workspace plan (paid vs trial) for kodoai.xyz send limits | Owner |
| 7 | Add mailboxes (each needs warm-up and DNS check) for 200/week | Owner |
| 8 | Richer signal sources (Instagram/Facebook posts, Google Business updates, job boards, news; needs search budget or Apify social scrapers; not measured) | Owner decides; assistant measures |
| 9 | Deferred Minor review findings (below) | Assistant, when relevant |
| 10 | Fix stale docs: `.env.example` lacks `SERP_API_KEY`/`SERP_PROVIDER`; `docs/handoffs/` are stale; CLAUDE.md pass list omits `followups`, `mailbox`, `import-history` | Assistant |

**Minor (deferred), copied from the ledger:** clean.py `seen` excludes operator-rejected domains; same owner_email across different domains in one run; bounce substring match (ajo@ vs jo@); quote-cut regex can cut an opt-out that starts "On..."; HTML-only replies collapse to one line so quoted history is not stripped; bare "Stop." with no object goes to the model; `sent_at` uses local date with UTC time and Outreach page uses UTC date; Touch 3 can follow Touch 2 by a day after deferral; leads with no reachable pages are never re-judged; `reason_to_respond` shown unlabeled; groq/serper costs have no batch_id so those dashboard columns are 0; Serper out of credits stops the whole enrich run; `test_sending_lives_only_in_send_py` greps one file only.

## 10. Known gotchas and traps

- DB tests (`-m db`, most of them) hit the **real** Supabase project. One pytest process at a time. They must delete only their own rows (`tests/support.py purge_test_suppression`); an earlier cleanup keyed on reason alone deleted real suppression rows.
- Supabase MCP destructive SQL asks for a confirmation that expires after 2 minutes; the user must approve promptly (the 0005 migration expired twice). Two Supabase MCP servers exist (`mcp__supabase__` needed re-auth; `mcp__plugin_supabase_supabase__` worked).
- PostgREST bulk inserts need identical keys on every row. The API caps reads at 1000 rows: always use `gtm.db.fetch_all`.
- macOS `sed -i ''`. The harness once blocked an oddly quoted multi-line shell command as a possible `rm`; keep shell commands simple.
- `.gitignore` contains a catch-all `.*` and `*.csv`: new dotfiles are ignored unless tracked (`.env.example` is tracked). An earlier stale `data/` rule hid `gtm/data/`; `tests/test_packaging.py` guards that.
- Gemini free tier is flaky; Groq 8K tokens/min is the real throttle; do not feed the full MedSpa Touch-1 prompt (26 KB) to the model.
- Check `.env` for stale leftovers from the old project (POSTGRES_*, REDIS_*, PROXY_*, META_*, BROWSER_WORKERS, CACHE_TTL_*, etc.): `config.py` ignores them. Many provider keys (Apollo, Snov, Lusha, ContactOut, RocketReach, Tomba, Prospeo) are in `.env` but unused by code.
- Draft requires `selected` AND `approved=true` (set on the Review page); selecting alone drafts nothing.
- Follow-ups are held (not cancelled) if another lead at the same company was already emailed.
- Notion history is a snapshot; the OS cannot see anything sent from Notion until re-imported. Batch03 is still running there.
- `uv run` must be executed from the repo root here (pyproject is at root). The root `CLAUDE.md` is the short OS version; the old Pakistan-scraper CLAUDE.md is gone.
- Postal address, ad-disclosure and opt-out line are blank on purpose; do not "fix" them.
- Test count in the ledger is stale; run the suite for the current number.

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
