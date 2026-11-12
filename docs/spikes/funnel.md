> **SUPERSEDED / STALE (banner added 2026-11-12).** Written before the move to Vertex Gemini as primary and before the finder changes. Current LLM facts: `docs/HANDOFF.md` section 7 (LLM rows). Owner-finding measurements: `docs/spikes/owner_routes.md`. Kept as history; do not rely on its conclusions.

# Task 7 gate: funnel estimate and decisions (2026-11-10)

Target: **200 ready-to-email leads a week** (named decision-maker, verified email, US). All rates are from one metro (Houston) and small samples; treat them as a first estimate, not a forecast.

## Measured rates
| Step | Rate | Source |
|---|---|---|
| Apify price | $0.004/place, +$0.001 with the website filter | `docs/spikes/apify.md` (120 + 73 places) |
| Survives cleaning (on-ICP by categories list or name, not closed, domain not duplicated) | **about 63%** (measured by running the real `clean_decision` rule over all 237 unique places bought in the spikes: 155 kept, 22 no website, 49 off-category, 4 day spa, 4 chain, 3 closed; then about 6 duplicate domains). The 84% figure in A2 was for the best tiles; the three-query set returns noisier places | Task 9 |
| Hunter returns any email | 42% (19 of 45 domains), 1 credit each, 0 if empty | `docs/spikes/hunter.md` |
| Hunter gives a verified decision-maker with a title | **9%** (4 of 45) | same |
| Signal found and lead selected | **not measured** | needs Tasks 10-12 |

## What 200 ready leads a week costs with Hunter alone
- Domains needing a Hunter search: 200 / 0.09 = about 2,200 a week, from about 3,500 raw places a week (2,200 / 0.63).
- Apify: 3,500 x about $0.006 = about **$21 a week (about $90 a month)**.
- Hunter: 2,200 x 42% = about 930 credits a week, **about 4,000 credits a month**. Starter (2,000 credits, $49/mo or $34/mo yearly) covers about half of the target, about 100 ready leads a week; Growth (10,000, $149/mo or $104/mo yearly) covers it. Pricing from hunter.io/pricing, read 2026-11-10.
- Signals and selection will cut the 200 further; that loss is not in these numbers.

## Sending capacity
200 new leads a week with Touch 1, 2 and 3 is about 600 emails a week, 85-120 a day over 5-7 sending days. A single mailbox warmed at 15-30 a day cannot do that soon. At a cap of 40 a day per mailbox that is **3 mailboxes** (Soban has said they will add mailboxes; each needs its own warm-up).

## Decisions needed from Soban (hard gate; no pipeline code starts until answered)
1. **Hunter plan.** Recommendation: do not buy yet. Free credits left: about 131 now (keys 1, 3, 4), plus key 2 resets 15 Nov. Task 10 first tests an owner-name lever (scrape the lead's own About/Team page for the founder or owner, then Hunter Email Finder, 1 credit only when found) on those free credits. If that lifts yield well above 9%, Starter may be enough.
2. **Apify budget.** About $13 of free credit left until 2026-11-24 ($1.48 of the first $10 key used on spikes); at about $21 a week that buys under one week of full-volume scraping.
3. **Paid fallback.** None recommended yet (`docs/spikes/enrichers.md`): Task 10 tests the free Prospeo (88 credits) and Tomba (25 searches) first.
4. **Send ramp.** Proposed defaults: start 10 a day, add 5 a day, cap 40 a day per mailbox.

## Soban's answers (2026-11-10)
1. Hunter: **do not buy yet**; test the owner-name lever on free credits first (Task 10).
2. Send ramp: **start 10 a day, add 5 a day, cap 40 a day per mailbox** (matches the `.env` defaults).
3. Apify budget: "let's wait for that for now": use free credit only; **no paid Apify top-up** until Soban says so. Soban also asked why the scrape looked poor and for optimised queries: answered in `docs/spikes/apify.md` A2.
4. Paid fallback: none (not asked; stays as recommended).
