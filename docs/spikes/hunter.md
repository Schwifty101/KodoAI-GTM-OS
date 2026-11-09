# Spike B: Hunter Domain Search on Houston med spas (2026-11-10)

Domains came from the Task 2 Apify run (`docs/spikes/apify.md`). Scripts: `scripts/spike_hunter.py` (5 domains, key 1) and `scripts/spike_hunter_bulk.py` (40 more, key 3). No personal emails are stored or printed. Free-plan credits only; spend logged in `cost_log` (`spike:*`).

## Measured (45 domains total)

| | 5 domains (key 1) | 40 domains (key 3) | Combined |
|---|---|---|---|
| Domains with any email | 1 | 18 | 19 (42%) |
| Domains with a personal (non-role) email | 0 | 9 | 9 (20%) |
| Domains with a personal **verified** email | 0 | 6 | 6 (13%) |
| Domains with a decision-maker title (founder, owner, CEO, president...) | 0 | 4 | 4 (9%) |
| Decision-maker title **and** verified | 0 | 4 | 4 (9%) |
| Credits used | 1 | 18 | 19 |
| Accept-all domains | 2 | 9 | 11 |

- **Cost: 1 credit per search that returns at least one email, 0 for an empty search.** 18 credits for 18 domains with results, though those domains had 75 emails between them. Hunter's pricing page (read 2026-11-10) says "1 credit per email found" and "bulk Domain Search 1 credit for up to 10 emails"; the measurement at `limit=10` matches the second, not the first. Trust the measurement and re-check on a paid plan.
- **Titles are the bottleneck.** 41 of 75 returned emails (55%) had no position at all, so under the spec's rule (title must establish a decision-maker) they are `no_buyer`. Titles that did appear: franchise owner (3), CEO (2), general manager (2), registered nurse (2), plus one each of marketing associate, VP operations, director of corporate sales, CFO, COO.
- **Filtering by `seniority=senior,executive&type=personal`** returned 0 on the two domains tried (both had 0 unfiltered too); no evidence either way on whether it saves credits.
- **Role addresses are common:** the only email on one domain was a generic support address (accept-all).

## What this means

Hunter Domain Search alone yields about **9% verified decision-makers per domain searched** (4 of 45; wide uncertainty on a sample this small, and one metro). To get 200 ready-to-email leads a week from Hunter alone you would search about 2,200 domains a week, using about 900 credits a week (42% of domains return results), roughly 3,900 credits a month.

Plan sizing, from Hunter's pricing page (read 2026-11-10): Free 50 credits; **Starter $49/mo ($34 billed yearly), 2,000 credits; Growth $149/mo ($104 yearly), 10,000; Scale $299/mo ($209 yearly), 25,000.** One shared pool across Domain Search, Email Finder and Email Verifier; Email Finder 1 credit per email found; Verifier 0.5 credit per verified email.
- Hunter-only at the target volume needs **Growth**.
- **Starter** covers roughly half the target (about 4,700 domains searched a month at 9% is about 430 buyers a month, about 100 a week).

## Recommendation for Task 10 and the gate

The lever is finding the owner's name, not buying more searches. Add an owner-name step before or beside Hunter: scrape the lead's own About/Team/Contact pages for a founder, owner or CEO name (free), then use Hunter Email Finder (name + domain, 1 credit only if found) and verify. This could lift yield well above 9% and make Starter enough. Not measured here; it is the first thing to prototype in Task 10 (its test count is small, so measure on the same 45 domains).
