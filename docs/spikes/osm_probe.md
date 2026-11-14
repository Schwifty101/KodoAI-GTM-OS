# OSM (Overpass) as a med-spa lead source: probe

Script: `scripts/osm_probe.py` (read-only on the DB; `uv run python scripts/osm_probe.py [area-substring]`). Run 2026-11-14.
Query per bbox: `nwr` with shop=beauty, beauty=*, healthcare=*, amenity=clinic|doctors, leisure=spa, amenity=spa, or name ~ `med ?spa|medical spa|aesthetic|botox|laser|skin|cosmetic`; `out tags center`.
Bboxes: Manhattan 40.70,-74.02..40.88,-73.91; Cary area 35.67,-78.95..35.85,-78.65 (includes Apex/Morrisville); Bluffton/HH 32.10,-81.00..32.35,-80.65.
Overpass was flaky: overpass-api.de returned 502, kumi mirror timed out. The first Bluffton attempt got 0 elements through failed requests (not a real zero); rerun alone returned 22.

| Measure | Manhattan | Cary area | Bluffton/HH |
|---|---|---|---|
| Elements | 1931 | 337 | 22 |
| Named | 1873 | 327 | 22 |
| website / contact:website / url | 880 | 190 | 9 |
| Phone | 1172 | 192 | 9 |
| addr:city / addr:state / addr:postcode | 747 / 685 / 1216 | 189 / 191 / 205 | 11 / 9 / 14 |
| opening_hours | 863 | 151 | 8 |
| ON_ICP (name or any tag value matches regex) | 134 | 26 | 3 |
| ON_ICP, name only | 88 | 21 | 3 |
| ON_ICP with a website domain | 90 | 15 | 0 |
| clean_decision keep, categories=[] (name regex only: med spa/aesthetic) | 8 | 5 | 0 |
| clean_decision keep, ICP hits given categories=["Medical spa"] | 84 | 15 | 0 |
| No domain (unusable under `domain:<d>` key) | 1051 (54%) | 147 (44%) | 13 (59%) |
| No name | 58 (3%) | 10 (3%) | 0 |

Cross-check, Manhattan (our 71 Apify leads, batch of coverage tile 'Manhattan'; leads table holds 127 distinct domains in total):
- Our 71 found in OSM: 5 by exact domain, 4 by fuzzy name (SequenceMatcher >= 0.85, no city filter). About 7%.
- OSM candidates with a website new to our whole leads table: 872 of 880 (all), 87 of 90 ICP-matching.
- Serper's 78 Manhattan places: no list saved, not compared.

Assumptions: leads built as name, website, domain from tags, state from addr:state, categories=[] (OSM has none). `clean_decision` "keep" with categories=[] therefore only passes on the name regex, which is the strict, honest number. The second row assumes every ICP hit would be tagged "Medical spa" (optimistic: it only exercises website, US, school, chain rules). The ICP regex includes "skin", "laser", "cosmetic", so it also hits dermatologists, hair removal and cosmetic dentists; none were reviewed by hand.

Identity: OSM ids are node/way/relation numbers, no Google place id. Fallback key `domain:<domain>` is available for 46-56% of candidates only; ICP subset 90 of 134 (67%) in Manhattan. Chains and multi-location groups share a domain, same as today.

Coverage gap: no ratings, review counts, Google categories, closed flags or Google place ids. `reviews`-based ordering in run_clean and signals have nothing to read. Completeness: Manhattan strict med-spa-by-name is 88 in OSM versus 71 Apify leads that matched only 5-9 of OSM's, so the two sets barely overlap and neither is a superset. Our batches come from a "withWebsite" Google search, so they skew to listings with sites; OSM's skew is toward whatever mappers tagged. Suburban counts are thin (Cary 21, Bluffton 3 by name).

Verdict: OSM cannot be a primary source: it lacks ratings and categories that the clean/select steps rely on, only about half of candidates have a website (the key enrich needs), and a name-regex strict keep is 8 in Manhattan. As a supplement it has some value: 87 ICP-matching, website-bearing businesses in Manhattan are new to our table, and ODbL data (attribution required) can be stored indefinitely. Treat it as a discovery list that still needs a categorisation/verification step before clean, not a drop-in replacement for Apify/Serper.
