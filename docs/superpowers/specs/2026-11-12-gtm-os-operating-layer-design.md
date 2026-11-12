# GTM OS operating layer: design (2026-11-12)

Status: written from the brainstorm of 2026-11-12, **awaiting owner approval**. Nothing in this document is built. It builds on `2026-11-09-kodoai-gtm-os-design.md` (the pipeline, already built) and `docs/HANDOFF.md` (current state). Where this document is silent, those two and `CLAUDE.md` rule.

## 1. Intent

The owner (Soban, KodoAI founder, single operator) wants one system that runs a daily outbound loop to med spa owners: **find leads, verify the owner and a deliverable email, draft, review, send, and show the numbers so strategy can be adjusted after each batch.** The pipeline passes exist today as commands. What is missing is the operating layer: pages to see and steer it, a runner that does the work on its own, scheduled sending, a way to bring in the owner's existing Google Sheet leads, and complete metrics. The owner's words: "this OS is my GTM OS."

Success is the owner opening the app each day, seeing yesterday's numbers, spending a few minutes reviewing drafts and pressing one button, while scraping, enriching and sending-with-safe-timing happen without them.

## 2. Goals

1. **Home** shows, every time it opens: yesterday's total scraped leads, how many of those became verified owners, and how many emails were sent or leads used from yesterday's batch; plus one clear next action (for example "8 drafts waiting for review"). Light: not everything lives here.
2. **Dedicated pages** (section 5) for batches, scraping and coverage, leads, review, drafts, send, replies, the manual queue, metrics and settings.
3. **A runner** that executes scrape, enrich, signals, select, draft, reply reading and sending on a button press or a daily schedule, with no operator terminal (section 6).
4. **Scraping** that uses narrow Google Maps searches and walks the major US metros automatically, city by city and, for big metros, by narrower tiles, never repeating covered ground, inside a budget cap.
5. **Batches of 100.** Verified leads join the open batch across several days; at 100 the batch closes. Metrics are per batch, like the Notion batches.
6. **Drafts** written by Gemini under the `MedSpa/` rules, shown with the angle chosen, editable one at a time or in bulk (section 8).
7. **Sending** that the owner starts with one button, executed at random times through the day in each recipient's local US time, within safe volume (section 9).
8. **Metrics**: money spent per API, response rate, bounce rate, cost per verified owner; each per batch and per individual lead, **and over time: yesterday, weekly, monthly and quarterly** (section 10).
9. **Import of the owner's Google Sheet** and a **manual queue** that uses the same sheet (section 7).
10. **Wasted leads** are not discarded: named-but-no-email leads are retried when free credits reset, and feed the manual queue (section 11).

## 3. Non-goals

- Email copy and angle strategy. Parked by the owner: `docs/NEXT-email-strategy.md`. This design only provides what that work will need (angle stored per draft, per-angle metrics, editing tools).
- Multiple users, roles, or a customer-facing product. One operator, as today.
- Open or click tracking. No tracking pixels or links in emails.
- A CRM, a second source of truth, or a mobile app.
- Bypassing logins or captchas on any website.

## 4. Anti-goals (would be a failure even if it technically works)

- Any email to an unverified address, to someone suppressed or already contacted, or after a reply or bounce.
- Burst sending, or anything that risks blacklisting or spam marking of kodoai.xyz.
- Spending past a configured budget; an automatic job that silently burns credits.
- Losing or overwriting suppression rows; the Supabase secret key reaching a browser.
- Editing tools that let a draft skip the mechanical writing checks.
- Auto-sending without a human having approved the drafts and pressed send.

## 5. Pages

| Page              | Purpose                                                                              | Today                           |
| ----------------- | ------------------------------------------------------------------------------------ | ------------------------------- |
| Home              | Yesterday's numbers, next action                                                     | partly (a dashboard exists)     |
| Batches           | Batches of 100, funnel and leads per batch                                           | partly (batches are per scrape) |
| Scrape & Coverage | Cities and narrow tiles, search terms, run now or daily, budget cap, what is covered | missing (a command)             |
| Leads             | Filter, sort, evidence per lead                                                      | built                           |
| Review            | Approve or reject selected leads                                                     | built                           |
| Drafts            | Every draft with its angle; edit one or in bulk                                      | missing (edits happen in Gmail) |
| Send              | Capacity, window, schedule view, send button, pause                                  | missing (`send --confirm`)    |
| Replies           | Replies, bounces, opt-outs, mark booked                                              | partly                          |
| Manual queue      | Best named-but-no-email leads for ContactOut lookup                                  | missing                         |
| Metrics           | Spend, response rate, bounce rate, per batch and per lead                            | partly                          |
| Settings          | Mailboxes, caps and ramp, budgets, footer values, key status, DNS check              | missing (`.env`, CLI)         |

The UI stays a browser app that reads and writes the database; it does not run passes itself.

## 6. Runner (the owner delegated this choice; these are my calls)

- A **worker process** on a small always-on virtual machine in Google Cloud, region **us-west1** (the always-free machine type exists only in US regions; the database is in Tokyo; a US address also suits US websites). Free-tier terms and real latency to be verified before creating anything. The owner has a Google Cloud credit and Application Default Credentials set up.
- The UI and the schedule **add jobs to the database**; the worker takes them and runs the existing passes. A schedule adds the daily scrape; a short timer sends whatever scheduled email is due.
- Sending is spread across the day, so the runner must stay up through the send window. Gmail's API cannot schedule a send, so the OS does the timing itself. If the worker is down, scheduled sends wait and resume; they never burst to catch up.
- Provider keys and the Gmail login live in Google Secret Manager on the server, not in a repo file. The Supabase secret key stays script-side.
- The UI may stay on the owner's Mac. Hosting it online for phone access is a later, separate choice.

## 7. Google Sheet import and the manual queue

The owner's sheet "MedSpa" (link supplied in chat 2026-11-12; store in Settings, not in the repo) has tabs Utah, Newyork and Texas with different columns (Utah even has two stacked blocks). Analysis of 2026-11-12: 341 rows, 164 with an email.

- **Color rule (owner-confirmed):** any green cell in a row = email sent; any red cell = dropped (no owner found, bad signal, or any other reason); no color = unknown but still a potential lead. Coloring is per row but some cells were left uncolored; the mark can be on any cell.
- **Green rows** become "already contacted" suppression entries (most already are, from the Notion import). **Red rows** become "never use". **Uncolored rows with an email** (84; about 53 not already suppressed or already ours) become candidate leads.
- Candidates pass the same gates as scraped leads: suppression and already-contacted, domain dedupe, no day spas or other excluded categories, no registered-agent "owners" (Newyork has 14 rows labelled "service-of-process name"), email verification, and decision-maker title. Multi-email cells are split. Identity is Google place id when present (Texas and Newyork carry a Maps URL; Utah's second block has none), else domain.
- Each tab needs its own column mapping. The import is a one-time job plus re-runnable.
- **Manual queue:** each morning the OS writes the best named-but-no-email leads (owner name, domain, LinkedIn search link) to a tab of the same sheet. The owner fills the email column from ContactOut (about 5 a day); the OS reads the emails back, verifies each, and enriches the lead if it passes. The initial pool is the 38 Texas and 134 Newyork uncolored rows with no email, plus Houston leads saved as named-but-no-email.

## 8. Drafts and editing

- Drafts are written by Gemini under `MedSpa/` (the instruction documents are not changed here).
- The **angle** (vector and lane) is stored on every draft and shown next to it.
- **Per draft:** edit subject, opener and body.
- **In bulk:** the owner types an instruction ("warmer opener", "shorter"); Gemini rewrites the chosen drafts; the owner sees before and after and accepts or rejects; the mechanical checks (`check_draft`: word counts, banned phrases) re-run after every rewrite and a failing rewrite is not accepted.
- **Source of truth (my call):** the OS database holds the draft text; the Gmail draft is created or updated from it when the owner approves, so there is no divergence. Today Gmail holds the text and the UI cannot edit.
- Emails stay plain text, short, and simple to read (owner requirement).

## 9. Sending

- One **Send** button schedules the day's approved drafts; it does not blast. This button press is the explicit send action required by `CLAUDE.md`; the approval gate before it stays.
- **Volume:** start at 20 a day; ramp +3 a day to a cap of 40 per mailbox (settings already derived from sending history: RAMP_START 20, RAMP_STEP 3, DAILY_CAP 40). Today there is one mailbox, soban@kodoai.xyz (warmed about three months, MailReach warm-up continues). More mailboxes later, each with its own cap, warm-up and DNS check. Whether the cap also applies per sending domain is a builder question for when a second mailbox exists on the same domain.
- **Timing:** weekdays only; each lead's US time zone is derived from its state and city (split states handled); send times are random within a daily window in the lead's local time (my guess for the window: 9 to 4). Follow-ups go before new leads; replies are read before every send, so a reply or bounce stops that lead's remaining touches. Cadence stays Day 0 / 3 / 7, no Touch 4.
- **Follow-ups (owner decision, 2026-11-12):** Touch 2 (Day 3) and Touch 3 (Day 7) are drafted by themselves when due, after replies and bounces are read. They do **not** send on their own: each one waits in a **Pending follow-ups** list on the Send page until the owner approves it. Each row shows enough to judge relevance: business and owner, which touch, days since Touch 1 (and Touch 2) with their send dates, the original email as sent, the thread so far, the reply/bounce/opt-out check result and when it was last checked, the angle and evidence used, any flag (another lead at the same company was emailed; domain suppressed), the follow-up text, and the slot it would take (lead's local time). Leads that replied or bounced are skipped automatically and listed under **Skipped (flagged)** with the reason; an opt-out also goes to suppression. The owner can approve one, several or all; approved follow-ups are scheduled ahead of new leads. A follow-up not approved by its due day stays pending and is marked overdue; it never sends without approval.
- **Safeguards:** auto-pause when the bounce rate exceeds 5% over at least 40 sends (7-day window); a manual pause switch; a DNS health check (SPF, DKIM, DMARC) in Settings; plain text, no tracking, no links. Spam complaints cannot be seen through the Gmail API, so MailReach or Google Postmaster Tools is how those are watched.
- The footer fields (postal address, ad disclosure, opt-out line) stay empty by owner choice. Do not fill them.

## 10. Metrics

- **Spend per API** (Apify, Hunter credits, Prospeo credits, Serper, Gemini, Harvest if used), **per batch and per lead**. Today Serper, Groq and Gemini rows carry no batch or lead id, so per-batch spend is incomplete; every paid call must record its batch and lead.
- **Response rate and bounce rate**, per batch and per lead; **cost per verified owner** including the cost of leads that failed.
- **Funnel per batch** (scraped, cleaned, named, verified, selected, approved, drafted, sent, replied, booked) and **where leads die**.
- **Per angle** response rate once the angle is stored per draft.
- **Fetch failures** by reason, to see how often websites block us.
- **History (owner, 2026-11-12):** Home shows yesterday; the Metrics page shows the same numbers by day, week, month and quarter, with a custom range and comparison to the previous period. Every number is built from timestamped events (send, reply, bounce, cost) so history is never lost. The Batch01 to 03 sends already imported from Notion appear as historical totals so trends start from the first campaign (my call).
- **Budget meter:** month-to-date spend against the monthly budget (section 12), per API.

## 11. Enrichment changes and wasted leads

- **Page fetching:** direct fetch first; for pages that fail, Apify's website content crawler as a fallback; Serper stays for search. Measured 2026-11-12 on the Houston batch: direct fetch failed on 5 of 41 sites; Apify recovered text for 3 of those 5 at about $0.008 per site. No login or captcha bypass.
- **Retry later:** when Hunter and Prospeo credits reset, a monthly job re-runs the finders only for named-but-no-email leads (the name is already known). `--retry-no-buyer` exists; a retry never erases a saved email.
- **Waste buckets:** junk (kept so the place is never paid for twice), named-but-no-email (retry plus manual queue), no owner found (parked; retried only if the researcher improves).
- **Best-first enrichment** (rank by review count, rating, owner-run signals before spending credits) is a hypothesis to measure over the first batches, not a requirement.

## 12. Constraints

`CLAUDE.md` governs: Supabase Postgres is the only database; only `gtm/config.py` reads the environment; US only, no day spas; lead identity is Google place id; a signal needs a source URL and date; enriched means a named decision-maker with a verified email (`valid` and Hunter score at least 80, or Prospeo VERIFIED); suppression is checked before every draft and send; every paid call writes a `cost_log` row; never print or commit keys; the Supabase secret key is script-side only; RLS restricts every table to the operator.

Measured facts for sizing (as of 2026-11-12, Houston batch): 87% of scraped places survive clean; owner names found for about 62% of cleaned leads; verified owners about 17% of cleaned leads. Free credits: Serper about 2,050 queries left; Apify two keys about $4.90 and $8.00, usage cycles end 2026-11-24; Prospeo 83 credits, renews 2026-11-24; Hunter free keys.

**Budget (owner, 2026-11-12):** 25,000 to 30,000 PKR a month in total, covering the Hunter subscription, Apify, Harvest, Serper and every other API credit (about $90 to $105 at roughly 280 PKR per USD; rate not checked). The Google Cloud credit covers the server and Gemini for now. This is a hard constraint: the weekly lead volume the system aims for has to be re-derived against real prices in the plan, because 200 emailable leads a week may not fit. Settings holds the monthly budget and per-API daily caps derived from it; the runner refuses paid calls that would pass a cap.

## 13. Left to the builder

Database design for jobs, schedules, scheduled sends and time zones; how to keep jobs idempotent and avoid double sends; worker supervision and restarts; how the UI reflects job progress; the time-zone lookup source; the scheduling algorithm for random send times; the coverage model (city and tile lists, ordering); the Metrics queries; the Secret Manager wiring; migration of existing data into batches of 100.

## 14. Open items for the owner

- **Hunter plan:** owner will buy it once everything is finalised and a campaign can safely start using the OS. Until then the free keys are used. Which plan fits the budget is decided in the plan.
- **Verifying free-mail addresses** (Gmail, Yahoo and similar): still open and not for the owner to solve. Hunter's check cannot confirm a Gmail address the way it can a business one, so the builder tests how to do it (section 15, item 10) before the OS accepts any.
- **Workspace plan:** paid (owner, 2026-11-12), so the higher Gmail send limits apply; the OS cap stays far below them.
- **Second mailbox:** added after Batch04 completes, or once there is enough data to lean on a strategy and go full send.
- **Daily budget defaults:** derived from the monthly budget in section 12; the builder proposes them.

## 15. Calls made after the builder review (mine, not agreed by the owner; check these)

1. **What goes out:** the worker sends the stored draft text through the Gmail API (a normal send, in-thread with In-Reply-To for Touch 2 and 3). The Gmail draft is not what goes out; a Gmail draft mirror is optional and off by default. If the owner edits a mirror in Gmail it is ignored. The `CLAUDE.md` line "Edit drafts in Gmail; the Gmail draft is what goes out" must change with this.
2. **Gmail login on the server:** reuse the existing OAuth refresh token for soban@kodoai.xyz (Desktop client, Internal Workspace app, scopes `gmail.compose` and `gmail.readonly`; Internal avoids the 7-day refresh expiry). It is copied into Secret Manager once. No new Google approval is expected; to be verified when it is first used on the server.
3. **Sheet access:** a service account in the same Google Cloud project, shared on the sheet as Editor by the owner. Colors are read with the Sheets API formatting fields, not values.
4. **No place id:** sheet rows without a Google place id get a synthetic key `domain:<domain>` in the existing unique `place_id` column, so the uniqueness rule holds; a real id replaces it if one is found later.
5. **Budgets:** one daily cap per API in that API's own unit (dollars for Apify and Gemini; queries for Serper; credits for Hunter and Prospeo), set in Settings, checked before each paid call. Every paid call records its batch and lead. Defaults to be proposed in the plan, small and inside free credit.
6. **Worker down:** a scheduled send whose local window has passed moves to the next weekday window; it is not dropped and does not need re-approval. A slipped follow-up keeps its place in the sequence.
7. **Ramp:** counts days that actually sent. After an auto-pause the ramp restarts from 20. Follow-ups count against the daily cap and go first. A lead only gets a slot inside its own local window; overflow rolls to the next weekday.
8. **Browser and jobs:** the UI inserts jobs and schedule rows and edits drafts under the existing operator-only RLS (publishable key plus operator login). The bulk Gemini rewrite goes through the job queue, so the before/after view appears when the job finishes (seconds).
9. **Batches:** "100" counts verified owners that are selected and ready (not merely scraped). A lead's batch is fixed once assigned. Scraped and cleaned leads belong to a scrape run (today's batches table); spend is recorded against the scrape run and the lead, and the per-batch view is a join. The Houston run is a partial open batch. Home's "yesterday" means leads scraped the previous calendar day in the operator's configured time zone (default: the browser's); the Batches page shows the batches of 100.
10. **Free-mail check:** the builder's first task is a short spike on how to verify a Gmail-type address (test Hunter's verifier on known-good addresses). Default rule if it works: deliverable and score at least 80. If it does not, personal addresses stay out until another verifier is chosen.
11. **Manual queue order:** named owner, LinkedIn URL present, then review count and rating descending. A lead whose pasted email fails verification stays `no_buyer` and is not re-queued.
12. **Approval flow:** the lead approval on the Review page stays as built. On the Send page the owner sees the drafts that would be scheduled, can untick any, and the Send button is the final approval. There is no third approval step for Touch 1. Follow-ups have their own approval list (section 9).
