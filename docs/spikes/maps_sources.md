# Spike: cheaper Google Maps sources than Apify (2026-11-14, desk research, nothing run, no keys used)

Question: can tile scraping cost less than Apify `compass~crawler-google-places` (about $0.005 per place with `website: withWebsite`) without losing place ID, website, category or coverage. All prices are vendor-page snapshots from this session; "UNVERIFIED" means not on a primary page I could read.

## Funnel used (our numbers, `docs/spikes/tile_tuning.md`, `owner_routes.md`)
- Measured: 65% of places kept by the clean rule; a real tile gave 71 new, 48 cleaned for $0.40 (about $0.0083 per cleaned lead). 14% of unfiltered places have no website (apify.md).
- Verified owners: ~10-12% of kept (owner_routes.md: Prospeo 2/20 on known names; ~15% in tile_tuning). I use 11%. ASSUMPTION: the other vendors' places keep at the same 65%.
- Per kept = price per place / 0.65. Per verified owner = per kept / 0.11.

## Comparison

| Option | $ per request | Places per request / max per query | $ per place | $ per kept | $ per owner |
|---|---|---|---|---|---|
| Apify (today) | per place, $0.004 + $0.001 website filter | cap we set: 40 per query | 0.0050 | 0.0077 | 0.070 |
| Google Places (New) Text Search Enterprise | $35 per 1,000 requests (first 1,000 a month free) | 20; hard max 60 per query (3 pages) | 0.00175 | 0.0027 | 0.024 |
| Serper `/maps` | 1 credit, $1 per 1,000 credits on the $50 pack (credits per Maps call UNVERIFIED: sources say 1, one says 3) | about 20 (UNVERIFIED; one source says ~10); `page` param, each page billed | 0.00005-0.00015 | 0.00009-0.00027 (no website filter, kept ~0.56) | 0.0008-0.0025 |
| DataForSEO Maps SERP | $0.0006 per task standard queue (up to 100 results), $0.002 live | 100 per task, more depth = more 100-blocks | 0.000006-0.00002 | ~0.00003 | ~0.0003 |
| Outscraper | $3 per 1,000 records after 500 free ($1 above 100k) | billed per record | 0.0030 | 0.0046 | 0.042 |
| SerpApi Maps | subscription, about $1.25 per 1,000 places on the $25 plan (vendor-written comparison) | 20 per page, `start` 0,20,40; docs say stop at start=100 | 0.00125 | 0.0019 | 0.017 |

Serper per-owner and DataForSEO rows are nearly free; the real cost of those is engineering and field gaps (below), not money.

## (a) Google Places API (New), official
- Prices and free caps: Text Search Pro $32 / 1,000, 5,000 free a month; Enterprise $35 / 1,000, 1,000 free a month. https://developers.google.com/maps/billing-and-pricing/pricing . Free caps replaced the $200 credit in March 2025 (https://mapsplatform.google.com/pricing/).
- Fields: `websiteUri`, `rating`, `userRatingCount` are Enterprise tier; `types`, `addressComponents`, `businessStatus` (closed flag) are Pro. So a full lead record is the Enterprise SKU. https://developers.google.com/maps/documentation/places/web-service/text-search
- Paging: `pageSize` max 20, "a maximum of 60 results across all pages". Tile control: `locationRestriction` (rectangle only, categorical queries) or `locationBias` (rectangle or circle up to 50 km). So 60 per query, not 40 x deeper, and a dense tile needs sub-tiles. No website filter: we pay for 100% of places.
- 1,000 free Enterprise calls a month = up to 20,000 places a month at zero cost, about the whole walk volume.
- TERMS (the blocker): Place IDs may be stored indefinitely; lat/lng cacheable 30 days; "Business names, addresses ... don't copy and save"; "Don't export, extract, or scrape Google Maps Content for use outside the Services"; no derived content. https://developers.google.com/maps/documentation/places/web-service/policies . So the official API lets us keep `place_id` and re-fetch, not a lead table of names, websites, ratings, categories. Whether Google's Service Specific Terms name "lead generation" explicitly: UNVERIFIED (the terms pages were truncated in my fetch; read https://cloud.google.com/maps-platform/terms/maps-service-terms before any decision). Building the leads table as we do now is, on the policy page alone, not permitted. Not viable as the storing source.
- A compliant hybrid exists (store only `place_id`, re-fetch fields per use) but it re-bills Place Details on every pass and the cleaned/enriched pipeline stores name, website and category in `leads`. Reject.

## (b) Our own scraper
- Google Maps terms forbid scraping (same policy page). Practical: JS-heavy Maps, rotating residential proxies, CAPTCHAs and layout changes are the product Apify/Serper/Outscraper sell; a home-built one costs proxy money plus maintenance and carries the same terms exposure with none of the vendor in between. Reject (delete over patch).
- Why vendors do it: they run the scraping and proxies on their side and sell results; the terms exposure is theirs, we hold a vendor contract. That does not make it permitted by Google; it moves who does it. Treat Serper/DataForSEO/Outscraper as equal to Apify on this axis.

## (c) Vendors
**Serper `/maps`** (we hold a key; `POST https://google.serper.dev/maps`, header `X-API-KEY`, per the OpenAPI listing at https://apis.io/apis/serper/serper-maps-api/ ; schema not on that page)
- Params (third-party wrapper, https://deepline.com/docs/providers/serper/maps.md): `q`, `ll` ("@lat,lng,zoom", so tile control by lat/lng+zoom, not a rectangle), `page` (each page billed), `placeId`, `cid`, `hl`, `gl`; no `num` on this endpoint; fixed about 20 places; an empty page 2 still costs a call.
- Fields listed there: `title`, `address`, `latitude`, `longitude`, `rating`, `ratingCount`, `category` (single string), `phoneNumber`, `website`, `cid`. Not listed: `placeId` (the Apify wrapper says `cid` is the stable id; Serper's own response may also carry `placeId`: UNVERIFIED), city/state (parse from `address`), category list, closed flags. No website filter.
- Pricing: packs $50 / 50k credits ($1.00 per 1,000) down to $0.30 (https://costbench.com/software/web-scraping/serper/). Free trial 2,500 queries on signup (https://serper.dev). Credits per Maps call: UNVERIFIED. Credit expiry: sources conflict (6 months vs none).
- Gaps that matter: cid is not a `ChIJ` place ID, so identity breaks (`leads.place_id` unique, suppression and history keyed on it) unless the response also gives `placeId`. This is the single go/no-go item.
**DataForSEO** Maps SERP: $0.0006 / task standard, $0.0012 priority, $0.002 live; each extra 100 results one more unit; up to 100 results a task (https://dataforseo.com/pricing/serp/google-maps-serp-api). Coordinate search is by `location_coordinate`; field list (place_id, cid, domain, category, rating, address_info) not confirmed on the pages I could read: UNVERIFIED. A vendor-written comparison says the record is thinner than Apify's. Async queue (about 5 min) fits a worker job. Minimum deposit UNVERIFIED.
**Outscraper:** 500 free records (monthly: UNVERIFIED), $3 / 1,000 to 100k. Full Maps field set, so it is a drop-in at 60% of Apify's price, a modest saving. https://scrap.io/outscraper-pricing
**SerpApi:** subscription plans; `ll` + `start` paging; fields `place_id`, `data_cid`, `type`/`types`, `rating`, `reviews`; `website` not confirmed in the docs I read. https://serpapi.com/google-maps-api
**Other Apify actors:** a cheaper actor changes price by cents, not an order of magnitude; one Apify actor even wraps Serper (`umamidata/serper-google-places-scraper`), so the money is in calling Serper directly. Not researched further.

## Per-tile money
Today $0.20-0.40 per tile (two queries x 40). Serper, 2 queries x 2 pages = 4 calls = $0.004-0.012 per tile (if 20 per page and 1-3 credits). DataForSEO 2 tasks = $0.0012. Google 2 queries x 3 pages Enterprise = $0.21 (free within the allowance, but not storable).

## Recommendation
1. Cheapest option that keeps identity, website and category and stays no worse on terms than Apify: Serper `/maps` (we already pay them), IF it returns `placeId` (ChIJ). About 50-100x cheaper per place.
2. Google Places API stores only place IDs by policy, so it cannot be our lead store; own scraper and Outscraper (only 40% saving) are not worth it; DataForSEO is the fallback if Serper lacks `placeId`.
3. Cost to give up: no website filter (14% wasted places, still cheap), parse city/state from address, single category string, closed flag lost.
4. Keep Apify for dense tiles or as fallback until a Serper tile matches Apify's kept count on the same tile.
5. Smallest test below, about $0.01; owner approves.

## Migration path (code)
- New `serper_maps(run_input) -> (items, credits)` next to `run_places` in `gtm/apify.py` (or `gtm/search.py`, which already has the Serper key and `budget.require("serper", n)` / `log_cost("serper", ...)` pattern). It loops `queries x pages` and maps each place to the Apify item shape `place_to_lead` reads: `placeId`, `title`, `website`, `address`, `city`, `state` (regex on ", City, ST 12345"), `categoryName`/`categories` (from `category`), `totalScore` (`rating`), `reviewsCount` (`ratingCount`). Drop places with no website in code (replaces the Apify filter).
- `run_walk(db, run_actor, ...)` already takes a callable; `scrape_input` becomes a per-provider builder (`ll` from tile centre, zoom from tile size). `scrape_city` logs cost with provider "apify" and `usd`; log "serper" with credits instead. Serper daily cap (`cap_serper_queries_day`) is shared with search/research; give maps its own setting or the cap starves owner research.
- Stop rule: `escalate_at` uses places-returned versus cap 40; with 20 per page, use "page full" as the saturation signal.
- No schema change if `placeId` is returned; if only `cid`, do not migrate (it would duplicate every known lead).

## Smallest live test (NOT run)
- 3 requests, `POST https://google.serper.dev/maps`, `{"q":"med spa","ll":"@29.5996,-95.6349,13z"}` with `"page":1`, `2`, `3` (Sugar Land, TX tile, already in `leads` from the Apify spikes, so overlap is checkable read-only).
- Cost: 3-9 credits, under $0.01 (or free inside the 2,500 signup queries if still unused). Writes nothing to `leads`; log with `cost_log` note `spike:maps_sources` if the owner wants it recorded.
- Pass criteria: (1) credits charged per call (response `credits` field); (2) about 20 places per page and whether page 3 is non-empty; (3) every place has a `ChIJ...` `placeId` (not just `cid`); (4) `website`, `category`, `ratingCount`, address with state present; (5) at least 60% of the returned `placeId`s already exist in `leads` for Sugar Land (recall check versus Apify). Any of (3) or (5) failing: stop, do not migrate.

## Live Serper /maps test (2026-11-14, owner approved, about 33 credits in total, nothing written to the database)

Calls: `POST https://google.serper.dev/maps` with `{"q": ..., "ll": ..., "page": n}`, key from config, every call checked with `budget.require("serper", 3)` and logged (`cost_log`, note `spike:serper_maps`).

Measured:
- **Credits:** 3 credits per call, 20 places per call, so **0.15 credits per place**. USD per credit is NOT verified here (depends on the plan; at an assumed $0.001 a credit that is $0.00015 a place, about 33x cheaper than Apify's $0.005).
- **Fields returned (80 of 80 places):** `placeId` in Google's `ChIJ...` form (also `cid`, `fid`), `title`, `address` (city and state have to be parsed from it), `website` (77 of 80; 77 of 78 in the multi-query run), `types` (a list of categories, e.g. "Medical spa", "Skin care clinic"), `type`, `rating`, `ratingCount`, `latitude`, `longitude`, `phoneNumber`, `openingHours`. No closed flag was seen in the sample (not verified for closed places). So identity (ChIJ place id) is compatible with our `leads.place_id`; the earlier worry (only `cid`) did not materialise.
- **Paging:** `page` 2 and 3 worked with an `ll` parameter (60 places over 3 calls); `page` 2 returned HTTP 400 for a text-only query without `ll`. Text-only queries give the first 20 only.
- **Tile control is weak with `ll`:** the top result for `ll` at central Manhattan (zoom 13) was in Great Neck, Long Island. Putting the place in the query text ("med spa Manhattan, NY, USA") returned 20 results all with Manhattan addresses, so tiles are best expressed as query text with several query wordings, not as `ll` paging.
- **Overlap with Apify's Manhattan leads is low, and that is not a failure:** Manhattan is a saturated tile (Apify hit its cap of 40 on both queries), so each tool reads a different slice of hundreds of med spas. 5 query wordings (med spa, aesthetics clinic, botox, medical spa, laser hair removal) = 5 calls, 15 credits returned **78 unique places, 63 kept by the clean rule (batch-level rules ignored, so slightly high), 54 of them new to our database**, against Apify's 71 new leads and 48 cleaned for $0.40 on the same tile. Recall of Apify's 71: 13 percent. On Houston (a broad city query, less saturated) 11 of 20 results were already in `leads` (55 percent).
- **Not verified:** the USD price per Serper credit on our plan, credit expiry, whether results are stable across days, quality of the closed-place flag, whether a lower-density tile (Cary, Bend) gives similar yield per call, the Serper terms of service on storing and using the data (see `docs/spikes/google_maps_terms.md`).

Reading: a tile costs about $0.015 at the assumed credit price (5 calls) against $0.40 with Apify for a similar number of kept places in a dense tile, a saving of about 25x, with the same place-id identity. The two sources are complementary, not identical. Decision pending the Google/Serper terms review and the owner.
