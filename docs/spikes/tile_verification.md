# Tile verification (metros.csv vs Google Geocoding)

## Method
`scripts/verify_tiles.py` geocodes `'<tile>, <ST>, USA'` (components=country:US) for every row of `gtm/data/metros.csv`, plus each metro's principal city (first row). Flags: `status` (not OK), `state_mismatch`, `partial_match`, `bad_type` (result type not city/town/neighbourhood-like), `too_far` (haversine from the principal city over 60 miles for rank <= 35, else 45). Results cache to `docs/spikes/tile_verification.csv.cache.json` (local, git-ignored), so reruns only call for changed tiles.

## Price
Geocoding is an Essentials SKU: $5 per 1,000 requests, 10,000 free per month (figures from one pricing-page fetch, not cross-checked). About 1,300 requests first pass plus 14 for the fixes: inside the free tier; list price would be about $6.5.

## Results
- 1285 tiles checked. First pass: 24 flagged.
- 14 were real errors, fixed in `metros.csv` (ranks unchanged, principal rows kept):

| Metro | Old | New | Resolves to |
|---|---|---|---|
| Los Angeles | Brentwood, CA | Brentwood, Los Angeles, CA | Brentwood, Los Angeles (was Contra Costa) |
| Allentown | Whitehall | Whitehall Township | Whitehall Township, PA |
| Trenton | Hamilton | Hamilton Township, Mercer County | Hamilton Township, NJ (was Hamilton NY) |
| Jackson | Jackson (county) | City of Jackson | Jackson, MS (also clears Ridgeland, Flowood false too_far) |
| Jackson | Madison (county) | City of Madison | Madison, MS |
| Huntsville | Madison (county) | City of Madison | Madison, AL |
| Cedar Rapids | Marion (county) | City of Marion | Marion, IA |
| Indianapolis | Franklin (county) | City of Franklin | Franklin, IN |
| Nashville | Franklin (county) | City of Franklin | Franklin, TN |
| Baltimore | Canton ("Maryland") | Canton, Baltimore | Canton, Baltimore, MD |
| Erie | Fairview (ZIP elsewhere) | Fairview Township, Erie County | Fairview Township, PA |
| Augusta | North Augusta, GA | North Augusta, SC | North Augusta, SC |
| Davenport | Moline, IA | Moline, IL | Moline, IL |
| Davenport | Rock Island, IA | Rock Island, IL | Rock Island, IL |

- 8 flagged accepted as false positives, left alone: Arlington VA (county-city, bad_type), Daniel Island SC (neighbourhood, bad_type), Palm Beach Gardens / West Palm Beach / Wellington (Miami MSA members, 62-75 mi), Marco Island (Naples/Cape Coral MSA, 50 mi), Palm Desert (Riverside-San Bernardino MSA, 60 mi), Williamsburg VA (Virginia Beach MSA, 50 mi).
- Final: 1285 tiles, 8 flagged, all accepted. The live `coverage` table was updated for the 14 changed rows (all were pending).

## Threshold false-positive pattern
`too_far` fires on real but sprawling MSAs (South Florida, Inland Empire, Hampton Roads) and on principal cities whose own geocode failed (Jackson resolved to a county, which made its satellites look 160+ miles away). `bad_type` fires on county-cities and neighbourhoods. Real errors showed as county results, wrong-state results, or distances of 90+ miles.

## What this does NOT prove
Geocoding resolving a name is not the same as the Maps scraper's `locationQuery` behaviour. The tiles are unscraped except Houston and Manhattan, so "City of X" / "X Township" names are untested against Apify. A wrong tile still costs a scrape run; check `new_leads` on the first runs.
