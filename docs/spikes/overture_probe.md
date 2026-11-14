# Overture Maps places as a med-spa lead source: probe

Script: `scripts/overture_probe.py` (read-only on the DB; free public S3 read through DuckDB: `uv run --with duckdb python scripts/overture_probe.py`; duckdb is not a project dependency). Run 2026-11-14 on release `2026-10-21.0` (latest per stac.overturemaps.org). Takes about 5 minutes (two bbox scans over S3).
Bboxes: Manhattan -74.02,40.70..-73.91,40.88 (same as the OSM probe); Houston -95.85,29.45..-95.00,30.25 (covers Houston, Sugar Land, The Woodlands). Our side: Manhattan tile batch (71 leads) and Houston batch `e11d97b6` (60 leads).
Candidate filter: name matches `med ?spa|medical spa|aesthetic|botox|laser|skin|cosmetic`, or taxonomy hierarchy/alternates match spa|beauty|aesthetic|dermat|cosmetic|health|medical|clinic|doctor|surgeon.
ON_ICP = name regex or taxonomy contains med_spa/aesthetic/cosmetic/dermat/skin_care (broad: includes cosmetics stores, cosmetic dentists). STRICT = taxonomy `medical_spa` or name matches `med spa|medical spa`.

| Measure | Manhattan | Houston area |
|---|---|---|
| Candidates | 43,174 | 60,584 |
| Website | 32,397 (75%) | 45,549 (75%) |
| Phone | 36,538 | 53,407 |
| ON_ICP (broad) / with site | 3,438 / 2,861 | 3,919 / 3,305 |
| STRICT med spa / with site | 556 / 508 | 1,191 / 1,058 |
| STRICT with site and domain new to our `leads` table | 463 | 979 |
| STRICT confidence <.5 / .5-.8 / >=.8 | 72 / 63 / 421 | 146 / 185 / 860 |
| ON_ICP confidence <.5 / .5-.8 / >=.8 | 404 / 732 / 2302 | 521 / 810 / 2588 |
| Status not `open` (closed flag present) among candidates | 1,481 | 1,515 |
| `clean_decision` keep, categories=[] (name regex only) | 356 | 799 |

Recall against our Apify leads: Manhattan 57 of 71 (80%) found by domain (43) or fuzzy name >= .85 (49, no city filter); Houston 51 of 60 (85%) (domain 40, name 46). Only by the STRICT med-spa subset: domain match 25 of 71 (35%) and 29 of 60 (48%): many of our leads are classified by Overture as dermatology, skin care, laser etc., not medical_spa.
Top ON_ICP categories (Manhattan): medical_spa 504, dermatology 489, skin_care_and_makeup 441, cosmetics_and_fragrance_store 328, cosmetic_dentistry 244, spa 164, makeup_artist 144, laser_hair_removal 119. Houston: medical_spa 1012, skin_care_and_makeup 486, dermatology 281, spa 279, cosmetic_dentistry 249.
Sources of ON_ICP rows (first source): Manhattan meta 1564, BrightQuery 1027, Microsoft 559, Foursquare 234, AllThePlaces 48. Houston meta 2257, BrightQuery 925, Microsoft 481, Foursquare 176, AllThePlaces 72.

## Findings vs OSM
Far better than OSM (8 strict, 5-9 of 71 matched, no categories, no ratings): Overture has a real category taxonomy with `medical_spa`, 75% website coverage, a 0-1 `confidence`, `operating_status`, and matches 80-85% of our Apify leads. It has NO rating or review count (our clean/select ordering reads those), no Google place id, and no owner data. Houston strict 1,191 looks large next to our 60 leads: likely includes day spas, dentists tagged medical_spa and stale records (not hand-reviewed); not a precision measure.

## Identity
Overture ids are GERS ids (UUID-like), not `leads.place_id` (ChIJ). Options: add `source` + `source_id` columns, or use `domain:<domain>` (spec section 15.4; domain is present for 75%). Cross-source dedupe against Apify leads must be by domain (and name plus postcode), as done here. Chains share a domain, same as today.

## Licence (verified 2026-11-14)
- docs.overturemaps.org/attribution: the Places page has no single theme licence; it lists per-source licences: Meta, Microsoft, PinMeTo, Krick, RenderSEO, DAC, BrightQuery, Birdeye, Uberall, OpenTravel Alliance = CDLA Permissive 2.0; Foursquare = Apache 2.0 (Copyright 2024 Foursquare Labs, Inc.); AllThePlaces = CC0 1.0. "Some of the data sources ... require their own attribution".
- Release notes 2025-09-24 (docs.overturemaps.org/blog/2025/09/24/release-notes/): places are multi-licence by source property. Foursquare records are Apache 2.0: provide a copy of the licence, state changes with dates, keep the NOTICE text ("Copyright 2024 Foursquare Labs, Inc. All rights reserved."). CDLA-only subset = drop `source = Foursquare`.
- Data seen: ON_ICP licences CDLA-Permissive-2.0 3,156 / Apache-2.0 234 / CC0-1.0 48 (Manhattan); 3,671 / 176 / 72 (Houston). None is ODbL or share-alike, so storing is allowed. UNVERIFIED: the exact CDLA Permissive 2.0 text (no attribution beyond keeping the licence notice is the commonly stated reading; not read here). Not legal advice; the safe route is storing only CDLA/CC0 rows and the per-row `license`.

## Verdict
Supplement, worth a small build: a free, storable, categorised candidate list with websites, about 460 (Manhattan) to 980 (Houston) STRICT med-spa candidates with a website and a domain new to our table (not reviewed for precision). Gaps: no rating or review count, no closed signal beyond `operating_status`, no Google id, unverified precision. Use as discovery feeding `scraped` leads (filter confidence >= .8 and status open, keep `license` and source, drop Foursquare for simplicity), identity key `domain:<domain>`. Before any build: hand-review 30 STRICT rows per area for precision, and check that select/clean tolerate null rating/review_count. Does not replace Apify/Serper for ratings.

## Precision review (2026-11-14)
30 random STRICT rows per area (`uv run --with duckdb python scripts/overture_probe.py --dump`, seed 1, files written outside the repo). Judged by me from name, Overture category, domain and street address only; no sites were fetched, so "real" means "looks like a med spa / aesthetics clinic", not confirmed. n=30 per area: about +-17 points.

| Verdict | Manhattan | Houston |
|---|---|---|
| Real med spa / aesthetics, in area, usable website | 18 | 19 |
| Real, but no website or the "website" is youtube / linktr.ee / beacons.ai | 4 | 3 |
| Real, but outside the area (New Jersey addresses inside the bbox) | 3 | 0 |
| Not a med spa (day spa, retail beauty shop, physician office, wellness, pain, ketamine/IV, massage) | 4 | 8 |
| Unsure (confidence 0.09, no status) | 1 | 0 |
| **Precision as a business type** (real + no-site + out-of-area) | 25/30 = 83% | 22/30 = 73% |
| **Usable now** (real, in area, real website) | 18/30 = 60% | 19/30 = 63% |

Does the confidence filter (>= .8, the earlier suggestion) help? Not really. Manhattan: usable 18/30 becomes 17/24 (71%). Houston: 19/30 becomes 13/21 (62%) and drops 6 real med spas (confidence .27-.64 on genuine clinics). Confidence is a weak signal here: do not use it as the main filter.

Recurring false positives:
- Overture tags `medical_spa` on day spas and wellness places: "Sun & Bloom Day Spa", "N7 SPA", "Micro Beauty", "Skin Spa New York", "Bleu spa and beauty studio", "Natural Health Wellness Clinic", "Vigour Wellness", "Custom Care Wellness".
- Physician or non-aesthetic clinics: "North Lakes Pain Consultants", "Infuzed Ketamine & IV Therapy", a neurology practice.
- Retail: "Bdr Usa" (beauty shop).
- Bad websites on real businesses: youtube.com, linktr.ee, beacons.ai, `*.square.site`, `*.myaestheticrecord.com`, `pay.withcherry.com`.
- Bbox spill: Manhattan box includes Edgewater, Fort Lee and Cliffside Park NJ (addresses like "River Rd", "Lemoine Ave", "Anderson Ave", "NJ-93"). Filter on `region` and city, not the box alone.
- Missing website is common among real ones (4 of 30 and 3 of 30), and unusable here since enrichment needs a site.

Suggested filter (to test, not built): `region` in the tile's state; domain present and not a link-in-bio, video, booking or site-builder host (reuse `PLATFORM_DOMAINS` / `PLATFORM_SUFFIXES` in `gtm/clean.py`, add the ones above); keep rows whose name matches `med ?spa|medical spa|aesthetic|laser|skin|plastic surgery|derma` and drop names matching `day spa|wellness|pain|ketamine|\biv\b|massage|beauty (shop|supply)`; ignore confidence. Expected: about 60-65% of strict rows survive as usable today; the name rules should lift precision above that but were not re-measured (would need a second sample). Domain-new-to-us counts in the table above (463 / 979) should be cut by about 35-40% for planning: roughly 280 and 600 usable new candidates.
Next check, as before: null rating and review count through `clean` and `select`.
