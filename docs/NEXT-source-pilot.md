# NEXT: map source pilots (Serper Maps, Overture). Written 2026-11-14 for a fresh Claude.

Read `CLAUDE.md` and `docs/HANDOFF.md` section 0 first. Nothing here is built. Every step that spends money or migrates needs the owner's yes.

## Goal and why
Apify `compass~crawler-google-places` costs about $0.005 a place ($0.20-0.40 a tile). Owner decision 2026-11-14: Google Places data is NOT stored (policy, `docs/spikes/google_maps_terms.md`). Plan: (1) Serper `/maps` as a second scrape provider beside Apify, behind a setting; (2) a free Overture Maps test as a possible storable supplement. Serper: 3 credits per call, 20 places per call (0.15 credits a place); USD per credit is UNVERIFIED (at an assumed $0.001 it is about 33x cheaper than Apify). Live test numbers: `docs/spikes/maps_sources.md` (last section).

## PILOT 1: Serper Maps as `scrape_provider`

**Step 0 (owner, no code).** Owner reads the USD per credit on their Serper plan (dashboard or pricing page) and Serper's terms on storing/using results. Do not guess either. Stop if terms forbid storing.

**Design already decided (from the live test)**
- Tile = query text, not `ll`: `"med spa Cary, NC, USA"`. `ll` bias is weak (a Manhattan `ll` returned Great Neck) and `page` 2 returns HTTP 400 without `ll`. So one call = the first 20 results; get depth from several wordings: `med spa`, `aesthetics clinic`, `botox`, `medical spa`, `laser hair removal` (5 wordings on Manhattan = 78 unique places, 63 kept, 54 new, 15 credits).
- Map each Serper place to the Apify item shape `place_to_lead` (gtm/scrape.py) reads: `placeId` from `placeId` (ChIJ, same identity as `leads.place_id`), `title`, `website`, `address`, `city`/`state` parsed from `address` (", City, ST 12345"), `categories` = `types` plus `type` (clean_decision needs "Medical spa" in `categories` or an ON_ICP name), `categoryName` = first, `totalScore` = `rating`, `reviewsCount` = `ratingCount`. No closed flag seen: leave `permanentlyClosed` unset (so `closed` False) and note it as a known gap; `clean_decision` cannot reject closed places from Serper. Drop items with no `placeId` or no website in code (replaces Apify's `withWebsite`).
- Pattern to copy: `gtm/places.py` (`to_apify_item`, parked Google provider, no budget/cost_log inside) and `serper_search` in `gtm/search.py` (`budget.require("serper", n)` before, `log_cost("serper", ...)` after, key `get_settings().serper_api_key`).
- Escalation: `run_walk` (gtm/coverage.py) keeps running the next query only while the last returned `n >= escalate_at * max_places` (counted before dedupe), and flags the tile `saturated` if the last also filled. For Serper set effective `max_places` = 20 (a call returns at most 20), so "filled" = 20 of 20 (>= 16 at 0.8). Proposed query list for Serper: the five wordings above, in that order; stop at the first that returns under 16. `run_walk`'s `queries` and `max_places` args already allow this; `scrape_city` calls `run_actor(scrape_input(...))` and logs provider "apify" with usd, so it needs a provider switch (log "serper" with credits, usd None).
- Own cap: add `"serper_maps": "cap_serper_maps_credits_day"` to `CAP_KEYS` in `gtm/budget.py` (not in `USD`, so it counts `units`), default 300 credits (about 100 calls), so Maps cannot starve owner-research search under `cap_serper_queries_day` 700. Call `budget.require("serper_maps", 3)` per call and `log_cost("serper_maps", 3, None, ...)`.
- Setting `scrape_provider` (str, `apify|serper`, default `apify`) and `cap_serper_maps_credits_day` in `DEFAULTS` (`gtm/settings_store.py`); mirror BOTH in `web/lib/settings.ts` `SETTING_FIELDS` (group "Scrape walk" / "Daily caps"); `web/scripts/verify.mts` compares them to the Python defaults. Check how an enum/str is validated in `validSetting` and whether `settings.ts` has a select type; if not, use `str` and validate in Python.
- No migration expected (cost_log provider is text: verify before assuming; if a CHECK constraint lists providers, that is a migration and needs the owner's yes).

**Tasks (TDD, fake HTTP, no live calls)**
1. `gtm/serper_maps.py`: `to_apify_item(place) -> dict`, `parse_city_state(address) -> (city, state)`, `serper_maps(query) -> (items, credits)` (one `httpx.post` to `https://google.serper.dev/maps`, `{"q": query}`, no paging, `X-API-KEY`). Tests `tests/test_serper_maps.py`: mapping through `place_to_lead` and `clean_decision` (kept, no_website, not_us cases); city/state parsing on 3 real-shaped addresses; budget gate raises `BudgetExceeded` over cap and makes no HTTP call; one `cost_log` row per call (db-marked); no page parameter is ever sent.
2. Settings + web mirror + `CAP_KEYS` (tests: `uv run pytest -q tests/test_settings_store.py tests/test_budget.py`, then the `verify.mts` command in CLAUDE.md).
3. Wire the provider into `run_walk`/`scrape_city` and the `walk` CLI by `scrape_provider`; apify path unchanged by test.
Verify: `uv run pytest -q` green; commit; deploy only when the queue is idle.

**A/B (owner's yes first).** Tile: Cary NC (Raleigh) or Bend OR (less dense than Manhattan; `tile_tuning.md` has Apify numbers: Cary 28+12+4 new kept over three queries, Bend 20+9+7). Run the Serper provider on the tile, then Apify on the same tile (about $0.20-0.40; needs a temporary `cap_apify_usd_day` raise to 4.5 and the stored settings row deleted afterwards, as in tile_tuning). Delete the test batch's leads afterwards or run the Apify side read-only to a file. Compare unique new on-ICP (kept) places and cost.
**Adopt Serper as default if** kept-new per tile >= 80 percent of Apify's at under 20 percent of its cost (at the verified credit price). Otherwise keep Apify default and use Serper only for dense tiles' extra wordings. Report the numbers to the owner either way.

## PILOT 2: Overture Maps places (free, read-only, no DB writes)
Get the Overture places theme for the Manhattan bounding box and Houston (NOT Los Angeles: we hold leads only for Manhattan, 71, and Houston, 60). Read our `leads` read-only, match by normalised domain and by name plus postcode. Report: recall against our leads; website coverage; categories (is there a med spa / aesthetics category); confidence score distribution; the identity problem (Overture ids are not `leads.place_id`; a source+source_id key or the `domain:<domain>` key from spec section 15.4 in `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md` would be needed); the licence (CDLA Permissive for places: VERIFY on the Overture site, attribution terms). Reuse the style of `scripts/osm_probe.py` and `docs/spikes/osm_probe.md` (OSM had no ratings/categories, about half had websites, 5-9 of our 71 matched). Output `docs/spikes/overture_probe.md`; recommend supplement or drop. Must not touch the DB with writes.

## Open items NOT part of these pilots (see `docs/HANDOFF.md`)
First real send of the 8 selected Houston leads has not happened (owner approval on Review page); Plans 4 (drafts and sending), 5, 6 not written or built; email copy strategy parked (`docs/NEXT-email-strategy.md`); fallback LLM and Gmail send from the VM never run live.

## Do not
- Do not store Google Places data; `gtm/places.py` stays parked.
- Do not turn on the daily walk schedule (`walk_schedule_enabled` stays false).
- Do not top up Apify or spend any paid credit without the owner's yes; run nothing paid in Step 0.
- Do not commit `docs/spikes/tile_verification.csv.cache.json` or any Geocoding cache (Google lat/lng, cacheable 30 days only).
- Do not invent facts: unverified items stay marked UNVERIFIED until measured.
