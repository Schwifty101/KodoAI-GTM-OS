# CLAUDE.md

Start here for the current state: docs/HANDOFF.md

KodoAI GTM OS for med spa outreach. Spec: `docs/superpowers/specs/2026-11-09-kodoai-gtm-os-design.md`. Plan: `docs/superpowers/plans/2026-11-09-kodoai-gtm-os.md`. Outreach content rules live in `MedSpa/` and are not redefined in code. Operating-layer design: `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md`; six-plan roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md`. Settings, budget caps and the jobs queue live in `gtm/settings_store.py`, `gtm/budget.py`, `gtm/jobs.py`, `gtm/worker.py`.

## Commands
- `uv run pytest -q` runs the suite. Tests marked `db` hit the real Supabase project and clean up after themselves.
- `uv run python -m gtm.cli <pass>` runs a pass: scrape, clean, enrich, signals, select, draft, followups, send, replies. Also `enqueue <kind> -- <flags>` (queue a pass as a job) and `worker [--poll 15]` (run queued jobs; `send` is not job-runnable), `mailbox add|unpause` and `import-history FILE` (Notion history into suppression). `walk [--tiles N]` scrapes and cleans the next uncovered tiles of the coverage table; `seed-coverage` fills it from `gtm/data/metros.csv`; `tz-backfill` sets `leads.tz` (free). `select` now numbers batches of 100. `send` is a dry run unless `--confirm`, and reads replies first. `enrich` flags: `--limit`, `--named-only` (with `--retry-no-buyer`: only leads whose owner is already named), `--finders` (default `site,search,research,prospeo`; `hunter` and `harvest` opt-in), `--harvest-budget`, `--research-budget`, `--retry-no-buyer` (spends credits again).
- `bash deploy/deploy.sh gtm-worker us-west1-b` deploys committed HEAD to the VM; the worker runs there under systemd (runbook: `docs/runbooks/cloud-runner.md`). Deploy only when the queue is idle.
- `cd web && npm run dev` runs the UI locally (login: email link to the operator address). The UI has no send button in v1: sending is `uv run python -m gtm.cli send --confirm` (spec section 7: passes run as commands). Edit drafts in Gmail; the Gmail draft is what goes out.
- `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts` checks the UI's write actions against the real database under RLS; `verify_scrape.mts` and `verify_batches.mts` (same invocation) check the `/scrape` and `/batches` pages' queries and writes. `uv run python scripts/verify_tiles.py` checks coverage tile names with the Geocoding API. The UI also has `/scrape` (coverage, Run N tiles now, retry failed tiles) and `/batches` (batch status, Retry later for named no_buyer leads).

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
