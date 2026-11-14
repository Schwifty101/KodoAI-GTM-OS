# Geoapify Places (and open POI sources) as a lead source

Date 2026-11-14. Read-only research, no key, no calls. Quotes are from pages fetched today. UNVERIFIED = page unreadable or silent.

## Verdict
The owner's belief is TRUE as to Geoapify's own Places page, but only that one page says it; the Terms and Pricing pages are silent. The catch is the data: it is OpenStreetMap, which has no ratings, no reviews, and thin med-spa coverage. Storage is legal; it is probably not a good lead source on its own.

## 1. Data source
- places-api page: "Geoapify Places API primarily utilizes OpenStreetMap (OSM) as its primary data source." apidocs: "We use the OpenStreetMap as the data source." Place Details: data returned "only if it's present in the OpenStreetMap database", and OSM "might be incorrect or outdated."
- "Primarily" is not defined; no other source is named (UNVERIFIED). Treat coverage as raw OSM plus Geoapify indexing: no added business data.
- https://www.geoapify.com/places-api/ , https://apidocs.geoapify.com/docs/places/

## 2. Fields, filters, limits
- Places response (GeoJSON points): name, country, state, postcode, city, street, housenumber, lat/lon, formatted, address_line1/2, categories, distance, place_id. Website, phone, opening_hours are NOT documented on the Places list page.
- Place Details (separate request per place) documents: `website` ("Official website."), `contact.phone` ("Main phone number."), `opening_hours`, wikidata/wikipedia. Rating: "Not documented" (none; OSM has no ratings or review counts).
- place_id: "Unique identifier for the place." Kind (OSM id vs Geoapify hash) UNVERIFIED. Stability across data refreshes UNVERIFIED.
- Category ids that exist: `service.beauty`, `service.beauty.spa`, `commercial.health_and_beauty`, `commercial.health_and_beauty.cosmetics`, `healthcare`, `healthcare.clinic_or_praxis`, `healthcare.clinic_or_praxis.dermatology`. No `beauty`, `beauty.spa` or "wellness" key; `leisure.spa*` are sauna/bath. No med-spa or aesthetics category: med spas will be tagged inconsistently (spa, beauty, clinic) or not at all.
- Area filters: `circle` (metres), `rect` (bbox), `geometry` (stored geometry id), `place` (boundary id); POST also `polygon`, `polyline`.
- Limits: "The maximum number of places you can request is 500." default 20, `offset` zero-based for paging.

## 3. Pricing
- Free: "3,000 credits / day", no card, up to 5 req/s. Paid (per month): API 10 $59 (10k/day, 12 req/s), API 25 $109, API 50 $179, API 100 $299, API 250 $609, Custom from $860.
- Places: "requires 1 credit when the limit is 20 places or less"; more than 20 = 1 credit plus 1 per 20 returned ("Every 20 places returned cost 1 credit"; 115 places = 6 credits).
- Place Details: "1 credit plus requested features costs".
- Metro tile of 300 places: about 16 credits list only. Adding Place Details per place for website/phone: about 300 more credits. So about 316 credits/tile, i.e. about 9 tiles/day on free, or 190 tiles/day list-only. Whether `website`/`phone` come in the list response for OSM places is UNVERIFIED (a test settles it).
- Credits shown are for list calls only; actual spend is nowhere near the $59 tier for our volume.

## 4. Terms
- places-api page: "you are allowed to cache, store, and redistribute the results obtained from the API". Apidocs sidebar: "Cache/store results with no limits." No duration limit stated.
- Attribution: "As a minimum requirement, you must provide attribution to OpenStreetMap (OSM) as the data source." Free plan adds: "if you are using the Places API on a free plan, you are also required to provide attribution to Geoapify." Terms: "Geoapify attribution is mandatory when using Free subscription plan."
- Terms (https://www.geoapify.com/terms-and-conditions/): silent on storing, caching, lead lists, resale, bulk export. Licence is "non-exclusive, non-transferable, non-sublicensable". Free plan: "commercial use ... is allowed in the development and, with some limitations, in the production phase": the limitations are not defined (UNVERIFIED, ask support). Also "distributing API requests among multiple accounts ... to fit into lower pricing plans is prohibited", and no "unreasonable or disproportionately large load".
- OSM data is ODbL: storing a database of it carries share-alike on a derivative database and attribution (Overture page flags the same). Internal use for outreach is generally fine; do not publish or redistribute the table. This is my reading, not legal advice.
- The Pricing and Place Details pages contain no caching statement, so rely on the Places page and get the sentence in writing if volume grows.

## 5. Quality
- No med-spa-specific comparison of OSM or Geoapify versus Google found (two searches). Only indirect: a SafeGraph vendor benchmark reports OSM at "26% coverage and 39.8% fill rate" and weakest in suburbs (vendor, not independent); LocationIQ (vendor) says Google POI data is strong on hours, phones, reviews while OSM is "good in certain geographies". Expect low recall for US med spas. The only way to know is to sample our existing Google-sourced med-spa leads in one metro and count matches.

## 6. Other open sources (one line each)
- Foursquare OS Places: Apache 2.0 ("Licensed under the Apache License, Version 2.0"), "20+ attributes and over 1000 place categories"; website/phone/hours fields per page UNVERIFIED; free bulk dump, no per-request cost. Storable with no attribution fee. No Google-style rating (FSQ rating/tips are not in the open set; UNVERIFIED).
- Overture Maps Places: CDLA Permissive 2.0 or Apache 2.0, "contains no OpenStreetMap data"; ~88M records (Meta ~60M, BrightQuery ~16M, Microsoft, Foursquare, others); names, addresses (region, postcode), `websites`, `phones`, `confidence` 0-1, `taxonomy` and `basic_category` (the old `categories` field was removed Sept 2026); stable GERS `id`. Query by bbox via DuckDB or `overturemaps download --bbox=... --type=place`. Free. Probably the best open candidate: bigger than OSM, has website and phone, permissive.
- Who's On First: a gazetteer ("a big list of places, each with a stable identifier"); licence and POI coverage UNVERIFIED (page silent). Skip: boundaries, not businesses.

## Recommendation
1. Storable in `leads`: Geoapify (explicit, with OSM plus free-plan Geoapify credit; ODbL caveat), Overture (permissive, no attribution beyond licence notice) and FSQ OS (Apache). All three are legal to store; Google data is not.
2. Cost for the metro walk: Overture and FSQ OS: $0 (download and filter locally; compute minutes, not credits). Geoapify: free tier covers list-only walks (about 190 tiles/day); with per-place Details about 9 tiles/day, so a 3-day trickle or API 10 at $59/month.
3. What we lose versus Google: ratings, review counts, Google place ID (our current unique key; need a new `source` plus `source_id` key; schema impact), and freshness/recall for small independents. Signals (reviews, recent activity) depend on those. Hours and website are patchy. Enrichment still finds owner/email from website, so a name plus website is the minimum we need.
4. Best to test first: Overture (free, has website/phone/confidence, no OSM share-alike). Geoapify is second because it is a live API with category filter built in.

## Smallest live test (not run)
Overture, zero cost: `overturemaps download --bbox=-118.67,33.70,-118.15,34.34 --type=place -f geojson` (Los Angeles, one big tile), filter `basic_category`/taxonomy for spa/beauty/medical, count rows with website, then match by name+postcode against our existing Google-sourced LA leads. Pass bar: at least 60% of known med spas found with a website.
Geoapify, if wanted: one GET, needs a free key (owner signs up, no card):
`https://api.geoapify.com/v2/places?categories=service.beauty.spa,commercial.health_and_beauty.cosmetics,healthcare.clinic_or_praxis.dermatology&filter=circle:-118.2437,34.0522,20000&limit=100&apiKey=KEY` = 1 + 5 = about 5 credits (limit 100). Check: how many rows, do rows carry website/phone/hours, what place_id looks like. Then 5 Place Details calls (about 5 credits) on known med spas to confirm website/phone.
