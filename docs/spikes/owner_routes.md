# Spike: routes to an owner's name and verified email (2026-11-10 to 2026-11-11)

Test set: the 20 Houston leads (batch e11d97b6-41a0-4957-8d3d-6b1728f74d90) with no owner name after the first enrich run, unless noted. Small samples; everything below is counts from this session, not re-run for this doc. "Strict" = the code guard in `gtm/researcher.py` as first written; "relaxed" = the built version.

## Routes tried

| Route | What | Result | Cost | Verdict |
|---|---|---|---|---|
| Agentic researcher (`research` finder) | Gemini loop with web_search + fetch_page, code-validated name, then Hunter Email Finder | 3/20 names strict, ~5-7/20 relaxed. Live run: 10 new names, 2 new verified emails | ~100 Serper searches, 169 Gemini calls (~372K tokens), 3 Hunter credits | **Built, default finder.** Wrong-attribution risk, hence the guard |
| NPI Registry | Look up the owner by business in the free federal registry | 1 confident, 2 weak of 20 | Free | Not built. Cash-pay med spas rarely have an NPI; records stale |
| Third-party profiles | Yelp, BBB, Facebook, Instagram, LinkedIn company, RealSelf | 1/20 | Serper queries | Not built |
| Apify `scrapeContacts` add-on | Contact scrape on the Maps actor | 0 names (emails only) | $0.002/place on the free tier, on top of $0.004/place | Not used. The names add-on "Business leads enrichment" is ~$0.10/lead, untested; ~$430/month at 1,000 places/week |
| State business filings (Texas) | Officers from Secretary of State / Comptroller | Not measured. Filings blocked by the sandbox (DNS); open Comptroller data has no officers | n/a | Dead end here |
| Free site-email idea | Scrape an owner-named address from the site, verify with Hunter | 0/24 name-matched; sites publish info@ / concierge@ role addresses | Free | Dropped |
| HarvestAPI LinkedIn | Profile lookup + findEmail on a saved name | 0 emails in ~22 lookups | ~$0.004/profile | Opt-in (`harvest`) only. A name-only LinkedIn match can be the wrong person; the company must match |

## Name > email finders, on saved owner names

| Finder | Result | Cost / limits | Verdict |
|---|---|---|---|
| Prospeo Enrich Person | 2/20 verified (~10% on known-name leads) | 1 credit only on a find; no-match free; free plan rate-limited (calls spaced 2 s, 429 retried); no score field, VERIFIED counted as 100. 83 credits left, renew 2026-11-24 | **Built, default finder** |
| Hunter Email Finder | Main email source inside `site`/`search`/`research`: 19 credits for 4 enriched | 1 credit only on a find | Default (inside other finders) |
| Hunter Domain Search | 33 credits for 1 enriched lead (Houston run) | 1 credit per domain with results | Opt-in (`hunter`) only |
| Tomba | 0 | Free plan 5 requests/day | Not used |
| Snov API | Blocked on the free plan | n/a | Not used |
| Lusha | 0/8 | A miss still costs a credit | Not used |
| RocketReach | Not measured: monthly lookup limit hit | n/a | Not used |
| Apollo | Not measured: key lacks scope | n/a | Not used |
| ContactOut | API key returns only a sample payload (API not unlocked, needs a sales call). The owner's manual numbers came from the browser extension, 5 leads/day | n/a | Not used |

## Why leads still fail

- Of leads with a name, most fail at name > email: six Hunter emails were `accept_all` with scores 72-79 (fail both the status and the score rule); one chain CEO (ovme.com) was `valid` but Domain Search confidence was below 80.
- Funnel on the batch: 52 cleaned; names for ~62%; enriched 5 (first run), 8 (saved-name retry + Prospeo), 10 (after `research`), 9 after `ovme.com` (a chain) was rejected on a re-check against the current clean rules. `run_clean` only looks at `scraped` leads, so a re-check of already-cleaned leads is a one-off script.
- Wrong attribution (lesson): the researcher put the owner of Glow Medical Aesthetics, a different clinic, on Miliv Med Spa. The owner confirmed the correct owners for Miliv Med Spa and for one other lead (names kept out of this doc). Always check that the company matches.

## Economics (unverified projection)

- Scrape is ~$0.0087 per cleaned lead. Hunter and Prospeo credits are the real limit.
- 100-200 emailable leads a week needs on the order of 1,000+ scraped places a week at ~15-20% yield. Not measured at that volume.
