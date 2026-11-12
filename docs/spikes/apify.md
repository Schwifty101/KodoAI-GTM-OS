# Spike A: Apify Google Maps, Houston TX (2026-11-10)

Actor: `compass/crawler-google-places` (verified exists, id `nwua9Gu5YrADL7ZDj`), pay-per-event. Run on the $10 free key. Total spend **$0.8456** of Soban's $2 cap (logged in `cost_log`, notes `spike:*`). Script: `scripts/spike_apify.py`. Raw items kept in scratchpad only.

## Measured

| Run | Input | Places | USD | USD/place |
|---|---|---|---|---|
| A broad | "med spa", `locationQuery` "Houston, TX, USA", max 120, no filter | 120 (hit the cap) | 0.4802 | 0.0040 |
| B Sugar Land | same query, `website: withWebsite`, max 40 | 40 | 0.2002 | 0.0050 |
| B The Woodlands | same, max 40 | 33 | 0.1652 | 0.0050 |

- **Price confirmed:** $0.004 per place; the `website` filter adds $0.001 per place (filter-applied events = places). Start fee is negligible (about $0.0002 per run).
- **`website: withWebsite` works:** 73 of 73 filtered results had a website. Unfiltered, 103 of 120 (86%) had one. Filtering at the source costs $0.001/place but avoids paying $0.004 for the 14% with no website, so it is cheaper once more than 20% of places lack a website (here 14%: filtering costs about the same, slightly more). Either is fine; decide at Task 8.
- **Min cap:** Apify rejects `maxTotalChargeUsd` below $0.50 per run.
- **Coverage:** the broad search stops at 120 and every tile result was new: **0 of 73 tile places appeared in the broad 120**. One broad search per city is not enough; narrow tiles by suburb/neighbourhood are required. `locationQuery` "Suburb, TX, USA" works at suburb level. The Woodlands returned 33 (under the 40 cap), which suggests that tile was exhausted; not proven.
- **Category quality (the cleaning pass must handle it):** in A, `categoryName` = "Medical spa" for 89 of 120 (74%); in B, 46 of 73 (63%). The rest are Spa, Health spa, Facial spa, Skin care clinic, Medical clinic, Laser hair removal, Weight loss, Wellness center, Nurse practitioner, Gynecologist. Day spas appear, so the day-spa rule must key on category, not on the search term.
- **Data quality:** 117/120 and 73/73 were in Texas; 2/120 closed; 116/120 had a phone. `placeId` is Google's `ChIJ...` form. About 10 of 176 websites repeated across places (shared domains), so domain dedupe matters.
- **Fields worth keeping:** `placeId`, `title`, `website`, `address`, `city`, `state`, `categoryName`, `categories`, `totalScore`, `reviewsCount`, `permanentlyClosed`, `temporarilyClosed`, `phone`.
- **Not in base output:** no email field at all; `ownerDescription` empty for all 120. Owners and emails must come from enrichment. Social/email extraction needs the `scrapeContacts` add-on (not run).

## Not measured
- Cost of `scrapeContacts` and `scrapePlaceDetailPage` add-ons.
- Whether a tile can return more than 120, and how many tiles per US metro give full coverage.
- Price at scale (volume discounts or plan changes).

## Funnel inputs for Task 7 (Apify side only)
Cost per scraped place about $0.004-0.005. Keeping "Medical spa" and near categories retains roughly 63-74%. Hunter and signal losses are measured in the other spikes.

## A2: query optimisation on the Sugar Land tile (2026-11-10, $0.6304 more; Apify total $1.4760 of the $2 cap)

**Correction to the table above:** "63-74% Medical spa" used Google's single primary `categoryName`, which misfiles real med spas (27 of 193 places are med spas listed under Spa, Health spa, Skin care clinic, Facial spa or Laser hair removal, e.g. "EOV Med Spa" = Health spa). Counting a place as on-ICP when **"Medical spa" is anywhere in its `categories` list OR its name matches `med ?spa|medical spa|aesthetic`**: **162 of 193 (84%)**. What it still excludes is really off-ICP: day spas, dermatology, urology, foot care, coworking space, laser-training school. Task 9 uses this rule, not the primary category.

| Run (Sugar Land, website filter) | Places | On-ICP | Cost | USD per on-ICP place |
|---|---|---|---|---|
| B baseline, "med spa", max 40 | 40 | 33 (82%) | $0.2002 | $0.0061 |
| C four queries x 20: "medspa", "medical spa", "botox", "aesthetics clinic" | 78 (no duplicates) | 48 (62%) | $0.3902 | $0.0081 |
| D "med spa" + `categoryFilterWords` (medical spa, health spa, skin care clinic, laser hair removal service, facial spa) | 40 | 36 (90%) | $0.2402 | $0.0067 |

- **Query wording matters less than variety.** "medspa" returned 18 on-ICP places but only 1 that "med spa" had not already found: Google treats them as the same search. C's 17 extra on-ICP places over the baseline came from different intents ("botox", "aesthetics clinic"), which also have lower precision (10/20 and 12/18 on-ICP). The union of all three runs was 51 on-ICP places against 33 for the baseline alone, so one query per tile leaves about a third of the places unfound.
- **`categoryFilterWords` is not worth it.** Values must be lowercase entries from a fixed list (400+ allowed values; "medical spa" is one). It lifted precision from 82% to 90%, missed 1 of the baseline's 33 on-ICP places (a plastic-surgery practice that also runs a med spa), and bills an extra $0.001 per place for the field. The Python cleaning pass does the same job for free.
- **Recommended query set per tile:** "med spa", "aesthetics clinic", "botox" with the `website: withWebsite` filter and no category filter; classify afterwards with the rule above. Measured later by running the real clean rule (Task 9) over all 237 unique places from these spikes: **65% kept** (155), 63% after duplicate domains; so about $0.008-0.009 per kept place.
- **Not measured:** how many tiles a metro needs; whether tiles from other cities show the same overlap pattern.
