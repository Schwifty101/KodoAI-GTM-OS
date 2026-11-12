# GTM OS operating layer: plan roadmap

Spec: `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` (approved by the owner 2026-11-12, with the later decisions in its section 16).

The spec covers several independent subsystems, so it is built as six plans. Each plan ships working, tested software on its own and is written just before it is built, against the code as it stands then. **Only Plan 1 is written now.**

| # | Plan | Delivers | Spec sections | Needs |
|---|---|---|---|---|
| 1 | **Foundation** (`2026-11-12-plan1-foundation.md`) | Settings store, spend attribution (batch and lead on every paid call), budget caps, paid-Gemini gate, jobs table and worker, Settings page with spend meter and jobs panel | 6, 12, 15.5, 16 | nothing |
| 2 | Cloud runner | Always-on Google Cloud VM (us-west1) running the worker, Secret Manager for keys and the Gmail login, restart on failure | 6, 15.2 | 1 |
| 3 | Scrape and batches | Coverage model and metro walk, daily schedule job, narrow search tiles, batches of 100, retry-later job, Apify fetch fallback, lead time zone, Scrape & Coverage and Batches pages | 2.4, 2.5, 11, 15.9 | 1 (2 to run unattended) |
| 4 | Drafts and sending | Drafts stored in the database, per-draft and bulk (Gemini) editing, Send scheduler (recipient time zone, random times, ramp, pause), Pending follow-ups approval list, send via the Gmail API from stored text, Drafts and Send pages | 8, 9, 15.1, 15.6-15.8, 15.12 | 1, 3 |
| 5 | Sheet import and manual queue | Per-tab column mapping, color rule, candidate verification with Hunter's verifier, manual queue tab round trip, service-account access | 7, 15.3, 15.4, 15.10, 15.11 | 1 |
| 6 | Metrics, Home and Replies | History (day, week, month, quarter), per batch and per lead, cost per verified owner, per-angle, budget meter, credit warning, Home and Replies pages | 2.1, 5, 10 | 1, 3, 4 |

Order: 1, then 2 and 3 in either order, then 4, then 5 and 6. Plan 5 only depends on Plan 1 and can move earlier if the owner wants the sheet leads sooner.

Parked and not planned here: email copy and angle strategy (`docs/NEXT-email-strategy.md`).
