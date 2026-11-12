# KodoAI GTM OS for Med Spas: Design

> See also: the operating-layer design `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` and roadmap `docs/superpowers/plans/2026-11-12-gtm-os-roadmap.md` (the pipeline here is built; those describe what comes next). Current state: `docs/HANDOFF.md`.

Date: 2026-11-09. Owner: Soban (soban@kodoai.xyz). Status: draft for approval.

## 1. Intent

Soban sells to med spas (see `MedSpa/`). Finding leads and researching buying signals per lead are the two big problems. Drafting is solved by strict rules already in `MedSpa/`. Logging in Notion is confusing and per-batch metrics are hard to get.

This repo becomes a personal operating system for that outreach: find med spas on Google Maps (US only for now), discard the irrelevant, find verified owners and emails, find recent buying signals, pick who to contact, draft and/or send the emails, and see per-batch metrics. One UI, one database.

It is an internal tool for one operator, not a product. (swans.co was an example of the idea for law firms; nothing is being built for med spas to buy.)

## 2. Goals, non-goals, anti-goals

Goals
- 200 ready-to-email leads a week (named owner, verified email, selected), at low cost ("shouldn't break my bank"). Scraping is sized backwards from that number using funnel rates measured in the spikes.
- Save only the fields needed per lead, nothing else.
- Selection of who to email is automated; the operator reviews exceptions and approves in bulk.
- Per-batch metrics without manual counting.
- Draft and/or send, chosen per lead selection.

Non-goals
- Not a SaaS, no multi-user, no auth beyond the operator.
- No LinkedIn automation, no phone/WhatsApp outreach.
- No day spas (explicitly out). Med spa ICP gates live in `MedSpa/`, not here.
- No reuse of the deleted Pakistan scraper (still in git history at HEAD if ever wanted).

Anti-goals (a failure even if it technically works)
- Emailing someone twice, after an opt-out, or from a bounced address.
- Spending Hunter credits on leads the cleaning pass should have dropped.
- Damaging the `kodoai.xyz` sending reputation.
- A second source of truth that drifts from the first (the Notion problem).
- Fabricated signals. A lead with no real, sourced, recent signal is relevance-led or not selected, never given an invented signal.

## 3. Constraints and facts (verified unless marked)

- Sending mailbox: one Google Workspace mailbox, soban@kodoai.xyz. Verified 2026-11-09: MX Google, SPF, DKIM (google selector) present; DMARC is one record, `p=reject; sp=reject; adkim=s; aspf=s`. MailReach screenshots: 99% Gmail inbox rate, reputation 100, about 15-30 warming emails a day. Warm-up volume is far below planned cold volume.
- Hunter: four free keys (50 credits each; key 2 exhausted until 15 Nov). Soban will buy a paid plan. Plan not chosen. Per-search credit cost UNVERIFIED.
- Apify: two free keys, caps $5 and $10, cycle ends 2026-11-24. Per-place price UNVERIFIED.
- Groq and Gemini keys are in `.env` and valid (model lists returned). Free-tier rate limits UNVERIFIED.
- `.env` also holds keys for Apollo, Snov, Tomba, Prospeo, RocketReach, Lusha, ContactOut and SerpAPI. Plans and credits UNVERIFIED.
- Missing and needed: Google/Gmail OAuth credentials (Gmail API). Supabase project values are set.
- Google Maps ToS on scraping: general ToS clause UNVERIFIED. Soban accepted the risk using Apify.
- Gmail daily send limits for Workspace: UNVERIFIED.
- Apify Maps scraper returns about 120 places per search; coverage needs narrow searches (city, neighbourhood or tile). How `locationQuery` coverage behaves is UNVERIFIED.
- Social links need Apify's contact add-on (verified earlier), not the base output.

## 4. The pipeline (decided by Soban)

One row per lead, global identity = Google place ID. Passes move a lead through statuses:

`scraped` > `cleaned` (or `rejected`) > `enriched` (or `no_buyer`) > `signalled` > `selected` > `drafted` > `sent` > `replied` > `booked`
Side states: `bounced`, `suppressed`, `unsubscribed`.

1. Scrape: Apify Google Maps, narrow searches per US city, med spa queries. New places inserted; existing place IDs skipped.
2. Clean: plain Python, no LLM. Drops chains, wrong categories, day spas, closed, duplicates, and (my call) places with no website, since Hunter works from a domain. Reject reason stored.
3. Enrich: Hunter first for owner and verified email. A lead is `enriched` only with a named owner or decision-maker plus a verified personal email for that person. Role addresses (info@, contact@, hello@ and the like) never qualify. Leads that fail are `no_buyer` and are kept (not deleted) so they are not re-bought. If Hunter finds nothing, fallbacks in this order (my call): free scrape of the lead's own website, then one paid fallback chosen after checking the other keys. The source of each email is stored.
4. Signals: find recent buying signals per cleaned+enriched lead and judge them against the ICP gates and five evidence fields defined in `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md`. Output: vector (conversion recovery, capacity, rebooking and retention), signal-led vs relevance-led, the evidence with source URL and date.
5. Select: automated (see section 6).
6. Act: draft and/or send per `MedSpa/` rules (Day 0/3/7, no Touch 4).

Fields stored per lead are the minimum: place ID, name, website, address and city/state, category, rating and review count, owner name, owner email, email source and verification status, signal evidence, vector, touch status and dates, reject reason, batch ID. No raw scraper dumps.

## 5. Storage: Supabase Postgres, sole database (decided)

No Google Sheet. Tables (names are a call; shapes are the contract):
- `leads`: the fields above, `place_id` unique globally.
- `batches`: one per scrape+process cycle; the unit all metrics group by.
- `touches`: one row per drafted/sent email (lead, touch number, status, gmail message/thread ID, timestamps, outcome).
- `suppression`: emails and domains never to contact; checked before every draft and send.
- `cost_log`: spend and credits per call (Apify, Hunter, fallbacks, LLM), tagged to a batch and lead, so cost per lead is a query.

Row-level security on, UI uses the operator's login. The Supabase secret key never goes to the browser.

## 6. Selection automation (decided in principle, details are my calls)

Soban does not tick leads by hand. A lead becomes `selected` when it passes the ICP gates, has a verified email not in suppression, and has a sourced signal or qualifies as relevance-led per `MedSpa/`. An LLM (Groq or Gemini) writes the one-line reason shown in the Review page. Soban approves or rejects in bulk and can override any lead. The LLM never invents evidence: every signal needs a URL and a date, and a lead without one is not signal-led.

## 7. UI (fresh, small; decided: fresh and small, pages are my guess)

Next.js app reading Supabase.
- Leads: table with filters (status, batch, city, state, vector, has email), sort, row detail with evidence.
- Review: the auto-selected list with reasons; bulk approve or reject.
- Outreach: drafts to review, send controls, Day 0/3/7 due list, replies logged.
- Dashboard: per-batch metrics (section 9).
Passes run as commands in v1 (my call); buttons in the UI that trigger them are a later step, not v1.

## 8. Sending

- Gmail API as soban@kodoai.xyz from a script. The Gmail connector available in Claude Code sessions cannot be used by a script; OAuth credentials are needed.
- Draft-first: emails are created as Gmail drafts; sending is a separate approved action. Soban chose "draft and/or send".
- Daily cap with a ramp, default low (exact numbers are the builder's to propose and Soban's to approve). Auto-pause if bounce rate or spam complaints cross a threshold.
- Every send checks suppression and "already contacted" first.
- Replies are detected by polling the mailbox and written to `touches` (reply detection and classification method is the builder's to propose).
- DMARC is strict: only Gmail-origin mail from this domain passes. No third-party sending tool without DNS setup.

## 9. Metrics (approved by Soban)

Per batch: leads scraped, kept after cleaning, enriched with a verified email, had a signal, drafted, sent, bounced, replied, positive reply, booked. Plus Apify and Hunter spend per lead (and per verified email). Definitions of "positive reply" and "booked" are marked by Soban or classified by LLM then corrected by Soban (builder to propose).

## 10. Decided by Soban vs my calls

Soban decided: Apify for Maps; Hunter paid plus fallbacks; Supabase as the only database; a UI; fresh and small build, old repo deleted; one Workspace mailbox on kodoai.xyz, already warmed; draft and/or send; the metric list; save only necessary fields; no day spas; Groq and Gemini as cleaning/selection LLMs.

My calls, to check: stack (Next.js, Supabase, Python scripts); status names; drop leads with no website; fallback order; passes as commands in v1; signal sources (the lead's website, Google review data from Apify, Instagram and news via search); LLM role limited to judging and phrasing reasons, with rules and code doing the gating.

## 11. Unverified items to settle first (spikes before building the pipeline)

1. One small paid Apify run on one city: true price per place, whether the `website` filter works, radius and `locationQuery` coverage.
2. One Hunter search: credits per search (`X-Credits-Used`), what it returns for a med spa domain.
3. Groq and Gemini free-tier limits and whether either supports grounded search; pick the cleaning/judging model.
4. Plans and credits of the other enrichment keys, to choose the paid fallback.
5. Gmail Workspace sending limits and what the Gmail API needs set up.

## 12. Left to the builder

Schema details and migrations; the Apify query/tiling plan for the US; signal-finding implementation within the sources above; the LLM prompts; Gmail OAuth setup; send cap and ramp numbers; reply detection; UI layout; testing approach. Existing rules in `MedSpa/` (ICP gates, evidence fields, vectors, cadence, writing rules) are the source of truth for outreach content and are not redefined here.

## 13. Calls made after the builder check (mine; Soban to confirm while reading)

- Spikes in section 11 are a hard gate: no pipeline code until the Apify, Hunter and LLM numbers are measured and a funnel estimate (scraped > cleaned > emailed) is written down. Schema and `cost_log` can be built in parallel.
- ICP gates: the builder reads `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md` and implements the gates that are mechanical (category, chain, website, size, geography) as code. Gates needing judgment (relevance-led, signal quality) go to the LLM with the evidence fields as required output. Anything the builder finds fuzzy comes back to Soban rather than being guessed.
- Signals: v1 mandatory sources are the lead's own website and Google review data from the Apify scrape. Instagram, news and search (SerpAPI) are optional extras added only after their cost and plan are verified. A lead with no verifiable signal falls back to relevance-led or is not selected.
- Draft and send: chosen per selection on the Review page. Sending is a separate explicit approve action in the UI or a command; nothing sends from a draft automatically.
- Stop rules: a reply or bounce stops that lead's remaining touches. Crossing the bounce or complaint threshold pauses the whole mailbox until Soban clears it.
- Hosting: the UI runs locally in v1, single operator, so auth and RLS stay simple. Hosting is a later step.
- A batch is one scrape run (one city and query set), so metrics compare like with like.

## 14. Decisions from Soban after the builder check

- Target: 200 ready-to-email leads a week. Scrape volume is derived from measured funnel rates.
- Enrichment rule (Soban, confirmed): the buyer is a decision-maker, meaning someone with the authority to approve the purchase (founder, owner, CEO or equivalent), with a verified email. No role addresses, and no managers or front-desk staff. If Hunter cannot establish a person's title as one of these, the lead is `no_buyer`.
- Canada is out of scope for now. US only: no Canadian scraping, no Canadian leads, no CASL handling.
- Mailboxes: Soban will add more mailboxes. The design is multi-mailbox from day one: a `mailboxes` table, per-mailbox daily cap and ramp, per-mailbox pause, and leads assigned to one mailbox for their whole sequence. A new mailbox needs its own warm-up and DNS check before it is enabled. All mailboxes stay on kodoai.xyz unless Soban says otherwise, which keeps strict DMARC alignment working.
- Opt-outs are replies. The reply-detection pass classifies opt-out replies and writes the sender's address and domain to `suppression`, and stops that lead's sequence. Emails carry no compliance footer by default. A postal address, an ad-disclosure line and an opt-out line are supported but off by default (see Soban's decision below). Basis: the FTC's CAN-SPAM guide (read 2026-11-09), which requires accurate From/To/Reply-To, a non-deceptive subject, ad disclosure, a postal address, an opt-out method (a return email address qualifies), opt-outs honoured within 10 business days, and states no B2B exception. Penalties up to $53,088 per email (FTC, Jan 2024 figure). This is not legal advice.
- Soban's decision (2026-11-09): skip the whole footer for now: the postal address, the ad-disclosure line and the opt-out line. CAN-SPAM requires all three (FTC: a valid physical postal address; clear and conspicuous disclosure that the message is an advertisement; a clear explanation of how to opt out) and penalties run up to $53,088 per email. Three config values, `POSTAL_ADDRESS`, `AD_DISCLOSURE` and `OPT_OUT_LINE`, exist and are empty by default; if set, each is appended to every email. The builder does not add or invent any of them, and does not block sending on an empty value. Replies are still scanned for opt-outs (a recipient can ask to stop in their own words), and those are honoured automatically.
- The footer text is part of the template and is added by the sender code, not left to the drafting prompt. The opt-out processing deadline is 10 business days; the design target is same day.
