# Sending history of soban@kodoai.xyz, from the Notion tracker (read 2026-11-10)

Counts only; no addresses. Source: Batch01, Batch02, Batch03 databases (`Initial Sent`, `Status`, `Reply Type`, `Touch`).

| Batch | Touch 1 sent | Send days | Busiest day | Bounced | Negative replies | Out of office | Positive |
|---|---|---|---|---|---|---|---|
| Batch01 (4 to 29 Aug) | 97 | 15 | 12 | 4 (4.1%) | 0 | 1 | 0 |
| Batch02 (2 Sep to 7 Oct) | 89 | 13 | 13 | 6 (6.7%) | 4 | 1 | 0 |
| Batch03 (10 to 12 Oct) | 32 | 3 | 20 | 2 (6.3%) | 0 | 0 | 0 |
| **All** | **218** | | **20 (12 Oct)** | **12 (5.5%)** | **4** | **2** | **0** |

- Follow-ups: about 134 leads reached Cadence Complete (Touch 3), so roughly 500 cold emails went out in about 10 weeks. Busiest known day: 20 new leads plus follow-ups.
- **Nothing is logged after 12 Oct.** Batch03 shows 30 leads at Touch 1 with no Touch 2 or 3 logged, so either follow-ups were not sent or not logged.
- **Bounce rate was about 5.5%** across all batches, above the 3% the OS first assumed. A 3% rule over 20 sends would pause on a single bounce, which is why the pause thresholds were recalibrated (see `.env`: 5% over at least 40 sends).

## Settings derived from this (2026-11-10)
`RAMP_START=20` (the busiest day so far was 20 new leads), `RAMP_STEP=5` (matches MailReach's +4-6 emails a day), `DAILY_CAP=40`, `PAUSE_BOUNCE_RATE=0.05`, `PAUSE_MIN_SENDS=40`. These are judgment calls, not provider rules; I have not verified any external bounce-rate standard.
