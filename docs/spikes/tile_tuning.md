# Spike: tile tuning, query depth per tile (2026-11-13)

Question: how many Google Maps queries per tile, and at what per-query cap, give the most kept leads for the least Apify money. Script: `scripts/tile_tuning.py`. Actor `compass~crawler-google-places`, `website: withWebsite`, cap 40 per query, per-run cap $0.50. Nothing was written to `leads` or `batches`. Spend: **$3.129 over 20 runs** (owner approved up to $3.60), logged in `cost_log` with note `spike:tile_tuning`. The daily Apify cap was raised to $4 for the runs and restored (no stored row, default $2).

"New kept" = places not returned by an earlier query on the same tile and not already in `leads`, that the real clean rule (`clean_decision`) keeps. It ignores the batch-level rules (brand repeats, duplicate domains), so kept counts are about 2 points high (earlier measurement: 65 percent against 63).

## Measured (first run: six tiles; second run: Bend and Bluffton again with all three queries)

| Tile (density) | Query | Places | Cap hit | New kept | USD | Kept per $ |
|---|---|---|---|---|---|---|
| Plano TX (dense) | med spa | 40 | yes | 32 | 0.2002 | 160 |
| | aesthetics clinic | 40 | yes | 23 | 0.2002 | 115 |
| | botox | 40 | yes | 6 | 0.2002 | 30 |
| Scottsdale AZ (dense) | med spa | 40 | yes | 39 | 0.2002 | 195 |
| | aesthetics clinic | 40 | yes | 31 | 0.2002 | 155 |
| | botox | 40 | yes | 14 | 0.0002 (billing anomaly) | n/a |
| Franklin TN (mid) | med spa | 40 | yes | 34 | 0.1702 | 200 |
| | aesthetics clinic | 40 | yes | 10 | 0.2002 | 50 |
| | botox | 40 | yes | 6 | 0.2002 | 30 |
| Cary NC (mid) | med spa | 40 | yes | 28 | 0.2002 | 140 |
| | aesthetics clinic | 40 | yes | 12 | 0.1202 | 100 |
| | botox | 40 | yes | 4 | 0.1952 | 21 |
| Bend OR (small, run 2) | med spa | 33 | no | 20 | 0.1652 | 121 |
| | aesthetics clinic | 40 | yes | 9 | 0.1202 | 75 |
| | botox | 40 | yes | 7 | 0.2002 | 35 |
| Bluffton SC (small, run 2) | med spa | 19 | no | 10 | 0.0952 | 105 |
| | aesthetics clinic | 16 | no | 0 | 0.0802 | 0 |
| | botox | 25 | no | 1 | 0.1252 | 8 |

By query position (first run, six tiles): position 1 "med spa" 159 kept per dollar; position 2 "aesthetics clinic" 105; position 3 "botox" 50 (about 38 if the Scottsdale billing anomaly is replaced by the usual $0.20).

## Findings

- **Third query "botox" is not worth it.** It never beat half of the first query's yield (rule below) on any tile and averages 24-50 kept per dollar against 160 for the first query. Dropped.
- **Second query "aesthetics clinic" is worth it on most tiles.** Rule used: a further query is worth running while its kept per dollar is at least half of that tile's first query. It passed on Plano, Scottsdale, Cary and Bend, and failed on Franklin (50 against 100 needed) and Bluffton (0).
- **Early stop works on small tiles.** Bluffton's first query returned 19 of 40 (tile exhausted for that intent); its second and third queries added 3 and 7 new places and 0 and 1 kept, so stopping there saves about $0.20. Bend's first query returned 33 of 40, and its second query still paid (75 per dollar), so the escalation threshold must sit below 33/40 = 0.825: set at **0.8**. Bluffton (0.475) stops.
- **Dense tiles saturate cap 40.** Every dense and mid tile filled the cap on both queries, so those tiles hold more places than one pass reads. The cost per place is flat (about $0.005), and kept per place falls with rank within a query, but deeper reads (cap 60 or 80) and lower caps (20 or 30) were **not measured**. Cap stays 40; saturated tiles are flagged by `run_walk` for a later sub-tiling or deeper-cap decision.
- **Money context.** Apify cost per kept place is about $0.006 on the first query and about $0.01-0.02 on the second. After the funnel (about 15 percent of cleaned leads become verified owners, `docs/spikes/owner_routes.md`) that is roughly $0.04-0.13 of Apify cost per verified owner, small against Hunter and Prospeo credits. The query depth therefore matters less for cost than for not wasting Hunter credits on weak leads, which the clean and select passes handle.

## Caveats

- Six tiles, one run each; Bend's first query returned 32 places in run 1 and 33 in run 2 (Google results move), so single numbers are noisy.
- One run billed $0.0002 for 40 places (Scottsdale "botox"); cause unknown (Apify usage reporting or a free allowance). It is excluded from the per-dollar comparison.
- Two small tiles only; a metro of 1-2M people may behave between Franklin and Bend.

## Decision (settings defaults)

`walk_queries = "med spa,aesthetics clinic"`, `walk_max_places = 40`, `walk_escalate_at = 0.8`. Worst case per tile $0.40, typical for a small tile $0.10-0.20. At 3 tiles a day that is at most $1.20 a day.
