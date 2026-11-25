# Yield-aware walk and category filter (2026-11-25)

## Intent
Autopilot's first real run gave about 5 enriched leads for $2.40. Across all 341 leads that reached enrich, 48 (14%) came out enriched or better. The owner picked "scrape better-quality tiles" and "do both over a few runs". Measured hints (small samples, mixed sources): category "Medical spa" converts at 22%, every other category at about 3%; Texas about 26%, New York about 14%; review count and rating do not matter.

## Goals
- The walk spends its Apify dollars on tiles likely to yield more enriched leads, learning as it goes.
- Credits (Hunter, Serper) are not spent enriching low-yield categories.
- Each autopilot run reports enriched leads per dollar so the owner can compare runs.

## Non-goals / anti-goals
- No new paid source, no change to the enrich rule, no change to how autopilot stops. Do not freeze the walk on a few early results: it must keep exploring.
- A reversible change only: both behaviours have a setting that restores today's behaviour.

## Approaches (owner picked both, 2026-11-25)
- Yield-ordered tiles plus a category filter (picked): orders the walk and trims the pool, no schema change.
- Only reorder tiles: lower risk, does not save credits. Only filter: does not raise volume per tile. Both together, measured over a few runs, tells which one matters.

## Design
**1. Tile order (`gtm/coverage.py`).** `claim_tiles(db, n)` today takes pending tiles by `seq` (population rank, New York first). New: `tile_scores(db)` computes a smoothed enriched rate per state from leads (kept leads that reached enrich; enriched-or-better counts as success; prior = global rate weighted as 20 leads), and per metro once a metro has 2 or more done tiles. `claim_tiles` takes the highest-scoring pending tile, ties broken by lowest `seq`; every third claim (counted from tiles already claimed in coverage) is an exploration claim: the lowest `seq` pending tile of a state with fewer than 40 kept leads. Setting `walk_yield_order` (bool, default true); false gives today's plain `seq` order. Pure function over counts so it is unit tested without a database.
**2. Category filter (`gtm/clean.py`).** Setting `clean_category_strict` (bool, default true). When true, `clean_decision` rejects a lead whose Google category is not exactly "Medical spa" with reason `low_yield_category` (a distinct reason so a later query can revive them if the filter proves wrong). When false, today's rule (category or name match).
**3. Measurement.** `scripts/yield_report.py` (read-only): per state and per scrape run, scraped, kept, named, enriched; and per autopilot run window (`autopilot_started_at` to the next start, from `jobs`/`cost_log`): enriched leads, USD, enriched per dollar. No new table.
**4. Rollout.** One autopilot run per setting combination over a few runs; the owner reads the report between runs. The first run after the change uses both settings on.

## Constraints
- Tests use `TEST_` leads and fake coverage rows only; the real coverage table is read-only in tests.
- Existing walk tests keep passing with `walk_yield_order` false.

## Left to the builder
Exact smoothing constant, how the exploration claim is counted in the database, report formatting.
