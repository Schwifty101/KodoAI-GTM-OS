# CLAUDE.md

Start here for the current state: docs/HANDOFF.md

KodoAI GTM OS for med spa outreach. Spec: `docs/superpowers/specs/2026-11-09-kodoai-gtm-os-design.md`. Plan: `docs/superpowers/plans/2026-11-09-kodoai-gtm-os.md`. Outreach content rules live in `MedSpa/` and are not redefined in code. Operating-layer design: `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md`; six-plan roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`. Settings, budget caps and the jobs queue live in `gtm/settings_store.py`, `gtm/budget.py`, `gtm/jobs.py`, `gtm/worker.py`.

## Commands
- `uv run pytest -q` runs the suite. Tests marked `db` hit the real Supabase project and clean up after themselves.
- `uv run python -m gtm.cli <pass>` runs a pass: scrape, clean, enrich, signals, select, draft, followups, send, replies. Sending rules: see Sending below.
  - `enqueue <kind> -- <flags>` queues a pass as a job; `worker [--poll 15]` runs queued jobs (plus `check-drafts`, `redraft`) and the send tick on its own thread.
  - Sheet passes (read `sheet_id` from Settings; dry run unless `--confirm`; also worker job kinds): `import-sheet [--tab T]`, `verify-sheet --batch ID [--limit N]` (0.5 Hunter credit per email, bucket `hunter_import`, refuses without `--confirm`), `sheet-queue` (daily on the worker when `sheet_queue_on`), `sheet-paint`. Needs migration 0015 and the first real sheet write is a hard gate: see `docs/runbooks/cloud-runner.md`.
  - `mailbox add|unpause`; `import-history FILE` (Notion history into suppression).
  - `walk [--tiles N]` scrapes and cleans the next uncovered tiles of the coverage table; `seed-coverage` fills it from `gtm/data/metros.csv`; `tz-backfill` sets `leads.tz` (free). `select` numbers batches of 100.
  - `send` is a dry run unless `--confirm`.
  - If the Gmail token is rejected, delete `.secrets/token_<mailbox>.json` and rerun on the Mac to re-auth.
  - `enrich` flags: `--limit`; `--named-only` (with `--retry-no-buyer`: only `no_buyer` leads whose owner is named; `cleaned` leads are still processed); `--finders` (default `site,search,research,prospeo`; `hunter` and `harvest` opt-in); `--harvest-budget`; `--research-budget`; `--retry-no-buyer` (spends credits again; also processes cleaned leads).
- `bash deploy/deploy.sh gtm-worker us-west1-b` deploys committed HEAD to the VM; the worker runs there under systemd (runbook: `docs/runbooks/cloud-runner.md`). Deploy only when the queue is idle.
- `cd web && npm run dev` runs the UI locally (login: email link to the operator address). The UI has a Drafts page (sample-first review, edit in place, approve in bulk, regenerate a batch with an instruction) and a Send page (Today and Follow-ups tabs, Start sending, Pause). Edit drafts in the OS: the database text is what goes out.
- `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts` checks the UI's write actions against the real database under RLS; `verify_scrape.mts` and `verify_batches.mts` (same invocation) check the `/scrape` and `/batches` pages' queries and writes. `uv run python scripts/verify_tiles.py` checks coverage tile names with the Geocoding API. The UI also has `/scrape` (coverage, Run N tiles now, retry failed tiles) and `/batches` (batch status, Retry later for named no_buyer leads).

## Sending (single source)
- Drafts live in the database (`touches` statuses: drafted, held, edited, approved, scheduled, sending, sent, cancelled). The Gmail draft is created only at send time; the database text is what goes out.
- `send_tick` (`gtm/send.py`) on the worker is the one sender: it runs every 60 s while the `sending_on` setting is on (Start sending / Pause on the Send page). Terminal `send --confirm` forces one tick (sends what is due now; only `--confirm` reads replies first).
- Window: Mon-Fri 9:00-16:00 in the lead's local time (null tz = America/Chicago).
- `send_anytime` setting and `send --confirm --anytime` skip the window: REHEARSAL ONLY, keep off.
- Ramp: 20 on the first real sending day, +3 per sending day, cap 40 per mailbox; restart from 20 after an auto-pause (`mailbox unpause` sets ramp_from). The tick stamps today's allowance on the mailbox (`allowance_today`, `allowance_date`) and the Send page shows that stamp; there is no second formula.
- Auto-pause at 3% bounce over 20 sends (7-day window).
- Replies are read at most every 10 minutes per mailbox. A Gmail token or auth failure pauses that mailbox with a reason.
- Gmail runs on the Mac (interactive OAuth) and on the VM (token from Secret Manager; a headless worker never opens a browser).
- Rehearsal and manual test rows use the prefix `REHEARSAL_` (never `TEST_`: db tests delete every `TEST_%` lead). Run one pytest process at a time (`mkdir /tmp/gtm-pytest.lock`). A session fixture sweeps empty test-named batches left by `new_batch`; reply and send tests use a fixture mailbox, never the real one.

## Rules
- Supabase Postgres is the only database. `gtm/config.py` is the only reader of the environment.
- Statuses: scraped, cleaned/rejected, enriched/no_buyer, signalled, selected, drafted, sent, replied, booked; side states bounced, suppressed, unsubscribed.
- US only. No day spas. Lead identity is Google place ID, unique globally.
- A signal needs a source URL and a date. Never invent one.
- Enriched means a named decision-maker (founder, owner, CEO or equivalent) with a verified email. Role addresses never qualify. The email must have verification `valid` and score >= 80 (`accept_all` fails). Failed leads stay `no_buyer` but keep a saved name for retries.
- LLM: Vertex Gemini primary, Groq fallback (`gtm/llm.py`); replies use `gemini-3.1-flash-lite` (`complete_reply_json`, `gemini_lite_*` prices, unverified). Owner-finding measurements: `docs/spikes/owner_routes.md`.
- Check `suppression` and "already contacted" before every draft and send. A reply or bounce stops that lead's remaining touches. A bare decline reply ("not interested") is suppressed with reason `not-interested`; a wrongly suppressed lead is fixed in the database. Cadence is Day 0/3/7, no Touch 4.
- Footer values (`POSTAL_ADDRESS`, `AD_DISCLOSURE`, `OPT_OUT_LINE`) are empty by default: append if set, never invent, never block sending on empty.
- Every paid call writes a `cost_log` row. Never print or commit keys. The Supabase secret key is script-side only, never in the browser.
- Send is always a separate explicit action from draft.
