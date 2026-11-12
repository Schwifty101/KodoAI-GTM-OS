# Cloud Runner (Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `uv run python -m gtm.cli worker` runs unattended on an always-on Google Cloud VM (us-west1), restarts on failure, takes keys from Secret Manager, and two workers can never run the same live job.

**Architecture:** Replace the "one worker only" caveat with a per-job heartbeat (a running job is stale only when its heartbeat stops, not after a fixed 60 minutes). Run the existing worker under systemd on an e2-micro VM; a small script copies Secret Manager values into a root-only env file before each start. Deploy is `git archive` over `gcloud compute ssh`, so the VM holds no GitHub credentials. No new services, no containers, no lease table.

**Tech Stack:** Python 3.12 + uv, Supabase Postgres (migration 0009), systemd, `gcloud`, Secret Manager.

**Spec:** `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` sections 6, 15.2, 16. Roadmap: `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (Plan 2).

## Global Constraints

- `gtm/config.py` is the only reader of the environment. Never print or commit keys. The Supabase secret key is script-side only.
- Owner decision 2026-11-12: **activate the full Google Cloud account before 2027-02-09, with budget alerts**; `allow_paid_gemini` (off by default) stays the only Gemini spend guard.
- Budget 25,000-30,000 PKR a month at 276 PKR per USD is a hard constraint. **Every step that creates a billable resource needs the owner's explicit yes first.**
- Region **us-west1**, machine type **e2-micro** (always-free class). Free-tier terms, external IPv4 charge and latency to the Tokyo database are **unverified** until Task 4 step 2.
- `send` stays non-job-runnable (`ALLOWED` in `gtm/worker.py`); sending is Plan 4.
- Tests marked `db` hit the real Supabase project; one pytest process at a time (`mkdir /tmp/gtm-pytest.lock`).
- Parallelism: Task 1 (code) and Task 2 (deploy files) touch disjoint paths and can run as parallel agents. Tasks 3 and 4 need both.

## Review Focus

- Two workers at once: each job is claimed once and a live job (fresh heartbeat, old `started_at`) is never requeued. Pinned in Task 1.
- A worker killed mid-job (VM reboot, `systemctl stop`, OOM): the job returns to the queue after the heartbeat lapses, and fails after 3 attempts. SIGTERM marks it `cancelled`. Pinned in Task 1.
- A heartbeat write that fails (network blip to Tokyo) must not kill the job's thread or the pass. Pinned in Task 1.
- A required secret missing at boot must stop the service with a clear error, never start with empty keys. Pinned in Task 2.
- A new key added to `Settings.from_env` but not to the secrets list would be silently empty on the VM. Pinned in Task 2.
- e2-micro has 1 GB RAM: an enrich or clean pass could be OOM-killed. Task 3 adds swap and the smoke test runs a real pass.

---

### Task 1: Job heartbeat replaces the 60-minute stale rule

**Files:**
- Create: `supabase/migrations/0009_job_heartbeat.sql`
- Modify: `gtm/jobs.py`, `gtm/worker.py`
- Test: `tests/test_jobs.py`, `tests/test_worker.py`

**Interfaces:**
- Produces: `jobs.heartbeat(db, job_id: str) -> None` (sets `heartbeat_at = now`, never raises); `requeue_stale(db, older_than_minutes: int = 5) -> int` (now keyed on heartbeat); `worker.beating(db, job_id: str, every: float = 30.0)` context manager that heartbeats from a daemon thread while a job runs.
- Consumes: existing `claim`, `finish`, `run_one(db, run_pass)`.

- [ ] **Step 1: Write failing tests** in `tests/test_jobs.py` (db-marked, same `T`/`clean` fixture):
  - `test_heartbeat_keeps_a_long_running_job_from_being_requeued`: enqueue, `claim`, set `started_at` 2h ago, call `heartbeat(db, jid)`, assert `requeue_stale(db) == 0` and status still `running`.
  - `test_job_without_heartbeat_is_requeued_after_five_minutes`: claim, set `heartbeat_at` and `started_at` 6 minutes ago, assert `requeue_stale(db) == 1` and status `queued`.
  - `test_claim_sets_heartbeat_at`: `claim(db)["heartbeat_at"]` is truthy.
  - `test_heartbeat_swallows_errors`: `heartbeat(MagicMock(side_effect=Exception), "x")` returns None (no db needed).
  Existing stale tests set only `started_at` (heartbeat null): they must still pass, so the stale filter treats null `heartbeat_at` as `started_at`.
- [ ] **Step 2: Run** `uv run pytest tests/test_jobs.py -q`. Expected: the four new tests FAIL.
- [ ] **Step 3: Migration `0009_job_heartbeat.sql`**: `alter table jobs add column heartbeat_at timestamptz;` and `create or replace function claim_job()` identical to 0007 but also `heartbeat_at = now()`, with `set search_path = public, pg_temp` re-applied and the `revoke execute ... from public, anon, authenticated` repeated (replace resets function settings). Owner approves, then apply to the real project with the Supabase MCP `apply_migration` (additive, no data touched).
- [ ] **Step 4: Implement** in `gtm/jobs.py`: `heartbeat(db, job_id)` updates `heartbeat_at` for that id where `status = 'running'`, wrapped in `try/except Exception: pass`. `requeue_stale` filters stale rows with `.or_(f"heartbeat_at.lt.{cutoff},and(heartbeat_at.is.null,started_at.lt.{cutoff})")` in both its UPDATE statements (the `attempts >= 3` fail and the `attempts < 3` requeue); default `older_than_minutes=5`. Clear `heartbeat_at` on requeue.
- [ ] **Step 5: Run** `uv run pytest tests/test_jobs.py -q`. Expected: PASS.
- [ ] **Step 6: Worker tests** in `tests/test_worker.py` (no db): `test_beating_calls_heartbeat_while_the_block_runs` (monkeypatch `worker.heartbeat` to append to a list, `with beating(None, "j1", every=0.01): time.sleep(0.1)`, assert at least 2 calls and none after exit); `test_run_one_beats_during_the_pass` (patch `claim`, `finish`, `heartbeat`; run_pass sleeps 0.1 with `every` patched small via `monkeypatch.setattr(worker, "BEAT_SECONDS", 0.01)`; assert heartbeats recorded).
- [ ] **Step 7: Implement** in `gtm/worker.py`: module constant `BEAT_SECONDS = 30.0`; `beating(db, job_id, every=None)` starts a daemon `threading.Thread` looping `Event.wait(every)` then `heartbeat(db, job_id)`, sets the event on exit; wrap the `run_pass` call in `run_one` with it. In `main`: sweep `requeue_stale(db)` at startup and every 300 s (was hourly), and `signal.signal(signal.SIGTERM, signal.default_int_handler)` so systemd stop marks the job `cancelled` through the existing `KeyboardInterrupt` path. `# ponytail: heartbeat and stale cutoff both use the worker clock; a skewed VM clock of minutes would mis-stale jobs, use DB now() if that ever bites`.
- [ ] **Step 8: Run** `uv run pytest tests/test_worker.py tests/test_jobs.py -q`. Expected: PASS.
- [ ] **Step 9: Commit** `git add supabase/migrations/0009_job_heartbeat.sql gtm/jobs.py gtm/worker.py tests/test_jobs.py tests/test_worker.py && git commit -m "feat: job heartbeat replaces fixed stale window, SIGTERM cancels"`

### Task 2: systemd unit and Secret Manager loader

**Files:**
- Create: `deploy/gtm-worker.service`, `deploy/fetch_secrets.sh`, `deploy/secrets.txt`
- Test: `tests/test_deploy_files.py`

**Interfaces:**
- Produces: `deploy/secrets.txt` = one env-var name per line (`#` comments allowed; a trailing `?` marks optional). `fetch_secrets.sh` writes `/run/gtm/env` (mode 600, `NAME="value"` lines) and `/opt/gtm/.secrets/token_<mailbox>.json` from secret `gmail-token`, and exits non-zero naming the first missing required secret. The unit runs it as `ExecStartPre=+` (root), then `ExecStart` as user `gtm`.

- [ ] **Step 1: Write failing test** `tests/test_deploy_files.py` (no db):
  - `test_every_settings_env_var_is_in_secrets_txt`: parse every `s("NAME")`/`n("NAME", ...)`/`_keys(env, "NAME")` name out of `gtm/config.py` with a regex; assert each appears in `deploy/secrets.txt` (with or without `?`), except an explicit set of non-secret tuning names (`DAILY_CAP RAMP_START RAMP_STEP PAUSE_BOUNCE_RATE PAUSE_MIN_SENDS SIGNAL_MAX_AGE_DAYS POSTAL_ADDRESS AD_DISCLOSURE OPT_OUT_LINE GOOGLE_OAUTH_CLIENT_FILE`) which are not in the file.
  - `test_unit_restarts_always_and_loads_the_env_file`: unit text contains `Restart=always`, `EnvironmentFile=/run/gtm/env`, `ExecStartPre=+/opt/gtm/deploy/fetch_secrets.sh`, `ExecStart=/opt/gtm/.venv/bin/python -m gtm.cli worker`.
  - `test_fetch_script_fails_loudly_on_a_missing_required_secret`: run the script with `GCLOUD=false` (the script calls `${GCLOUD:-gcloud}`) and `GTM_ENV_OUT` pointed at a tmp path; assert non-zero exit, stderr names the secret, and the out file does not exist.
- [ ] **Step 2: Run** `uv run pytest tests/test_deploy_files.py -q`. Expected: FAIL (files missing).
- [ ] **Step 3: Write the three files.** `secrets.txt` required: `SUPABASE_URL SUPABASE_SECRET_KEY GROQ_API_KEY GEMINI_AGENT_PLATFORM_API_KEY SERP_API_KEY PROSPEO_API_KEY APIFY_API_KEY`; optional (`?`): `SUPABASE_PUBLISHABLE_KEY HARVEST_API_KEY APIFY_API_KEY_2..9 HUNTER_API_KEY HUNTER_API_KEY_2..9`. Script: `set -euo pipefail`, build output in a temp file then `mv` into `${GTM_ENV_OUT:-/run/gtm/env}` only on full success, `umask 077`, `chown gtm` for the token file. Unit: `User=gtm`, `WorkingDirectory=/opt/gtm`, `RestartSec=10`, `StartLimitBurst` generous (a bad secret must not crash-loop forever: `StartLimitIntervalSec=600`, `StartLimitBurst=5`).
- [ ] **Step 4: Run** `uv run pytest tests/test_deploy_files.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `git add deploy tests/test_deploy_files.py && git commit -m "feat: systemd unit and Secret Manager loader for the worker"`

### Task 3: bootstrap and deploy scripts

**Files:**
- Create: `deploy/bootstrap.sh` (runs once on the VM as root), `deploy/deploy.sh` (runs on the Mac)

**Interfaces:**
- Consumes: Task 2 files. Produces: `deploy/deploy.sh <vm-name> <zone>` which does `git archive HEAD deploy gtm pyproject.toml uv.lock | gcloud compute ssh <vm> --zone <zone> -- 'sudo tar -x -C /opt/gtm && sudo -u gtm uv sync --frozen --no-dev && sudo systemctl restart gtm-worker'`, then prints `systemctl is-active gtm-worker`. `bootstrap.sh` creates user `gtm`, `/opt/gtm`, a 2 GB swapfile (1 GB RAM), installs `uv`, copies the unit to `/etc/systemd/system/` and enables it (does not start it until secrets exist).

- [ ] **Step 1: Write both scripts** (`set -euo pipefail`; idempotent: re-running bootstrap changes nothing). `deploy.sh` refuses a dirty tree (`git diff --quiet` and `git diff --cached --quiet`) so the VM only runs committed code.
- [ ] **Step 2: Dry check locally**: `bash -n deploy/bootstrap.sh deploy/deploy.sh` and `shellcheck` if installed. Expected: no output.
- [ ] **Step 3: Commit** `git add deploy && git commit -m "feat: VM bootstrap and git-archive deploy scripts"`

### Task 4: provision, verify, smoke test (owner gates, sequential)

**Files:**
- Create: `docs/runbooks/cloud-runner.md` (commands run, what was verified, how to redeploy, rotate a key, read logs, stop the worker)
- Modify: `docs/HANDOFF.md` (section 0 a/e/f/j), `CLAUDE.md` (add `deploy/deploy.sh`), `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` (section 16: decision recorded)

Each numbered step marked **GATE** waits for the owner's yes in chat.

- [ ] **Step 1 (owner, console): activate the full account and set a budget alert.** Billing > Activate full account; Budgets & alerts: monthly budget at 20 USD with alerts at 50/90/100 %. Note for the owner: a budget alert warns, it does not cap. The free-trial credit keeps applying until 2027-02-09. Record the date done in the runbook.
- [ ] **Step 2: Verify free-tier terms and latency (read-only).** `gcloud compute machine-types list --zones us-west1-b --filter="name=e2-micro"`; read the current Compute Engine free-tier page and the external IPv4 price page and write the figures and URLs into the runbook (expected, **unverified**: 1 e2-micro/month free in us-west1, 30 GB standard disk free, an external IPv4 address billed at about 3.6 USD a month, about 1,000 PKR). Run a new `scripts/measure_db_latency.py` (20 `select id from batches limit 1` calls, print median ms) from the Mac now and again from the VM in step 5. **GATE: show the owner the monthly cost figure and the latency before creating anything.**
- [ ] **Step 3 GATE: create resources.** Service account `gtm-worker` with only `roles/secretmanager.secretAccessor`; one secret per name in `deploy/secrets.txt` (values piped from the local `.env`, never echoed) plus `gmail-token` from `.secrets/token_soban@kodoai.xyz.json`; VM `gtm-worker`, e2-micro, us-west1-b, 30 GB standard disk, that service account, `--scopes=cloud-platform`, no firewall rules beyond default SSH. Commands go in the runbook.
- [ ] **Step 4: Bootstrap and first deploy.** `gcloud compute scp deploy/bootstrap.sh gtm-worker:` then `sudo bash bootstrap.sh`; then `bash deploy/deploy.sh gtm-worker us-west1-b`. Expected: `active`.
- [ ] **Step 5: Smoke test, zero cost.** From the Mac enqueue a `send` job with payload `{"test": 1}` through the db (kind `send` is not runnable). Expected within 60 s: status `failed`, error contains `cannot be run by the worker`, proving the VM worker reached the database and drained the queue. Then run the latency script on the VM. Delete the test row.
- [ ] **Step 6: Failure drills.** (a) `sudo systemctl kill -s KILL gtm-worker`: expect restart within 10 s. (b) Insert a TEST job (`payload {"test": 1}`) as `running` with a fresh heartbeat and confirm the sweep leaves it; age its heartbeat 6 minutes and confirm the sweep requeues it, then delete it. (c) Reboot the VM: expect the worker active again and `/run/gtm/env` recreated.
- [ ] **Step 7: First real unattended pass (owner gate, costs money).** Ask the owner before enqueueing; suggest `clean` on the Houston batch (no paid API) as the first real job, and watch `journalctl -u gtm-worker` and the Settings jobs panel. Record RSS peak (`systemctl status`) in the runbook; if the pass is OOM-killed on 1 GB, record that and ask the owner about e2-small (paid) before changing anything.
- [ ] **Step 8: Docs.** Update the three files above: Plan 2 built, VM name and date, the activate-full-account decision, the heartbeat replacing the one-worker caveat (j), and remaining open items (budget alert exists; Gmail send from the VM is unproven until Plan 4).
- [ ] **Step 9: Commit** `git add docs CLAUDE.md scripts/measure_db_latency.py && git commit -m "docs: cloud runner runbook, handoff and decision record"`

## Self-review

- **Spec coverage (section 6):** always-on VM us-west1 (T4); worker takes jobs from the database (existing, hardened T1); keys and Gmail login in Secret Manager (T2, T4 step 3); restart on failure (T2 `Restart=always`, T4 step 6a); job lease (T1 heartbeat); free-trial decision (T4 step 1). Schedule job and send timer belong to Plans 3 and 4, not here.
- **Skipped on purpose:** a lease table, a worker-alive indicator in the UI (a queued job with no worker is already visible in the jobs panel), Docker, CI deploy, hosting the UI online. Add when a second worker or phone access exists.
- **Types:** `heartbeat(db, job_id)`, `requeue_stale(db, older_than_minutes=5)`, `beating(db, job_id, every=None)`, `BEAT_SECONDS` are used consistently in Task 1 and in the worker.
