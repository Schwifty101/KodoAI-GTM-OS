# Runbook: cloud runner (Plan 2)

Facts verified 2026-11-12 unless marked unverified. The worker runs on a GCP VM; the UI stays local.

## What exists

| Item | Value |
|---|---|
| Project | `gen-lang-client-0603350481` (full pay-as-you-go; upgraded before the trial end 2027-02-09) |
| VM | `gtm-worker`, e2-micro, `us-west1-b`, Debian 12, 30 GB pd-standard, public IP |
| Service account | `gtm-worker@gen-lang-client-0603350481.iam.gserviceaccount.com`, `roles/secretmanager.secretAccessor` (project level) |
| APIs | compute, secretmanager, cloudbilling (only to read prices; may be disabled), iap (pre-existing) |
| Unit | systemd `gtm-worker`; `Restart=always` |
| Secrets | 15 in Secret Manager, named as the env vars (SUPABASE_URL, SUPABASE_SECRET_KEY, GROQ_API_KEY, GEMINI_AGENT_PLATFORM_API_KEY, SERP_API_KEY, PROSPEO_API_KEY, APIFY_API_KEY, APIFY_API_KEY_2, SUPABASE_PUBLISHABLE_KEY, HARVEST_API_KEY, HUNTER_API_KEY .. _4), plus `gmail-token` |
| Loader | `deploy/fetch_secrets.py` (one Python process: metadata server + Secret Manager REST) writes `/run/gtm/env` at each start. The first loader called gcloud once per secret and exceeded the 90 s start timeout on the e2-micro (found in the kill drill) |
| Layout | `/opt/gtm` root-owned; user `gtm` owns only `.venv .cache .python .secrets` |
| Python | 3.14.10 on the VM (pinned by `UV_PYTHON=3.14` in `deploy/deploy.sh`), same minor as the Mac |
| gcloud (Mac) | 593.0.0 via Homebrew, logged in as the owner account |

Migration 0009 (`jobs.heartbeat_at`) is applied. A running job beats; a job with no heartbeat for 5 minutes is requeued. This replaces the 60-minute stale rule, so more than one worker is now safe.

## Cost

| Item | Cost |
|---|---|
| e2-micro, 30 GB standard disk, 1 GB North America egress | Free tier (docs page): 1 e2-micro per month in us-west1/us-central1/us-east1. No end date; Google may change it with 30 days notice |
| External IPv4 | $0.005/hour (Cloud Billing catalog) = about $3.65/month, about 1,000 PKR. The free tier does not cover it |
| Secret Manager, 15 secrets | about $0.6/month (**unverified** price) |
| Gemini | Pay-as-you-go now. `allow_paid_gemini` (Settings, off by default) is the only spend guard |

Budget alert "GTM OS monthly" (billing account 01F2D5-227412-E5D58D, filtered to this project): $20 USD, alerts at 50, 90 and 100 percent, created 2026-11-12 with `gcloud billing budgets create`. Alerts warn; they do not cap spend.

## Deploy (Mac, repo root)

```
bash deploy/deploy.sh gtm-worker us-west1-b
```

Ships committed `HEAD` only (`git archive`); the tree must be clean. Syncs deps, installs the unit, restarts the worker.

**Deploy only when the queue is idle.** The restart cancels a running job (`cancelled`, not requeued). `deploy/bootstrap.sh` was run once at setup; do not re-run it.

## Logs

```
gcloud compute ssh gtm-worker --zone us-west1-b
sudo journalctl -u gtm-worker -f
```

## Stop / start

```
sudo systemctl stop gtm-worker     # stop (a running job is cancelled)
sudo systemctl start gtm-worker
systemctl is-active gtm-worker
```

Or stop the whole VM from the Mac: `gcloud compute instances stop gtm-worker --zone us-west1-b` (a stopped VM may still bill for its disk and external IP, **unverified**).

## Rotate a key

```
printf %s "NEW_VALUE" | gcloud secrets versions add NAME --data-file=- --project gen-lang-client-0603350481
sudo systemctl restart gtm-worker    # on the VM; reloads /run/gtm/env
```

Update the local `.env` too. Never print or commit keys.

## Reboot behaviour

The unit is enabled, and `/run/gtm/env` is rebuilt from Secret Manager on every start, so a reboot needs no action. Verified: `kill -9` recovery within 30 s; a VM reset recovered on its own; a killed job is requeued after 5 minutes without a heartbeat.

## Verified live

- Smoke test: a `send` job drained and failed with "cannot be run by the worker" (as designed).
- Latency to the Tokyo database: median 162 ms from the VM, 230 ms from the Mac.

## Tearing down

```
gcloud compute instances delete gtm-worker --zone us-west1-b --project gen-lang-client-0603350481
gcloud secrets delete NAME --project gen-lang-client-0603350481    # each of the 16 secrets
```

Then delete the `gtm-worker` service account if unused. Queued jobs stay in the database and wait for any worker (the Mac works: `uv run python -m gtm.cli worker`).

## Open items

- Verified 2026-11-12: a real `clean` job on the Houston batch ran to `done` on the VM (output `{}`: nothing left to clean). Not verified: a heavy pass (enrich, signals) and the RAM peak under load on 1 GB.
- Not verified: RAM peak on 1 GB under a real pass.
- Not verified: Gmail send from the VM (Plan 4).
- If the VM's Python ever changes: empty `/opt/gtm/.venv` as `gtm` over ssh first, then redeploy (uv cannot remove it; `/opt/gtm` is root-owned).
