# Yield-aware walk and category filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** the walk prefers tiles likely to yield enriched leads, clean drops the 3% categories, and a report compares runs.

**Architecture:** a pure scoring function plus a changed `claim_tiles` in `gtm/coverage.py`; a `strict` flag on `clean_decision`; a read-only `scripts/yield_report.py`. No migration. Two settings, both reversible.

**Tech Stack:** Python, pytest, supabase-py.

**Spec:** `docs/superpowers/specs/2026-11-25-yield-aware-walk-design.md`

## Global Constraints
- Settings `walk_yield_order` (bool, default true) and `clean_category_strict` (bool, default true); false restores today's behaviour exactly.
- Success for a lead = status in enriched, signalled, selected, drafted, sent, replied, booked; "kept" = reached enrich (status not scraped, rejected, cleaned).
- Tests: `TEST_` leads and fake coverage rows; the real coverage table and real settings are never written; one pytest at a time (`until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done` ... `rmdir /tmp/gtm-pytest.lock`); long output to a file.
- Every agent: `ponytail:ponytail`, `superpowers:test-driven-development`, graphify before grepping, `superpowers:verification-before-completion`. Do not touch the untracked Codex files.

## Review Focus
- Tie or no data at all: order falls back to `seq`, never raises (Task 2).
- A state with tiny samples must not dominate: smoothing and the exploration claim (Task 2).
- `walk_yield_order` false equals the old order, including the existing `claim_tiles` tests (Task 2).
- Strict clean must not reject a lead whose categories contain "Medical spa" and must give the new reason only when the name would have saved it (Task 3).
- Report with zero kept leads or zero spend: no division by zero (Task 4).

## Task groups
Task 1 first. Then Tasks 2, 3, 4 in parallel (disjoint files). Then Task 5.

### Task 1: Settings keys
**Files:** Modify `gtm/settings_store.py`, `web/lib/settings.ts`; Test `tests/test_settings_store.py`, `web/scripts/settings_groups.mts`.
**Interfaces:** Produces `walk_yield_order: bool = True` (group "Scrape walk"), `clean_category_strict: bool = True` (group "Scrape walk").
- [ ] Failing test `test_yield_settings_defaults_and_types`; implement; run `tests/test_settings_store.py`, `settings_groups.mts`, `npx tsc --noEmit`. Commit `settings: yield walk keys`.

### Task 2: Tile scoring and `claim_tiles`
**Files:** Modify `gtm/coverage.py`; Test `tests/test_coverage.py`.
**Interfaces:** Produces `tile_scores(stats: dict[str, tuple[int, int]], global_rate: float, prior: int = 20) -> dict[str, float]` (pure: `stats[key] = (kept, success)`, returns `(success + prior*global_rate) / (kept + prior)`); `load_yield_stats(db) -> tuple[dict[str, tuple[int,int]], dict[str, tuple[int,int]], float]` (per state, per metro (only metros with 2 or more done tiles), global rate; one paged pass over leads joined to `coverage.scrape_batch_id`); `claim_tiles(db, n)` keeps its signature.
- [ ] Failing tests: `test_tile_scores_smooths_small_samples` (1 of 1 beats nothing; 1 of 1 scores below 20 of 40 at the same global rate); `test_tile_scores_unknown_key_gets_global_rate`; `test_claim_tiles_orders_by_score_then_seq_and_explores_every_third` (fake pending tiles in two states with fixed stats via a monkeypatched `load_yield_stats`: the third claim in a row is the lowest `seq` tile of a state with fewer than 40 kept); `test_claim_tiles_with_setting_off_is_plain_seq` (monkeypatched `setting`). Existing `claim_tiles` tests must pass unchanged with the setting patched to false.
- [ ] Run, expect FAIL. Implement; the exploration count is the number of coverage rows already `running` or `done` modulo 3 (document in a comment). Run `tests/test_coverage.py`, expect PASS. Commit `walk: order tiles by smoothed yield`.

### Task 3: Category filter in clean
**Files:** Modify `gtm/clean.py`; Test `tests/test_clean.py`.
**Interfaces:** Produces `clean_decision(lead: dict, strict: bool = False) -> str | None` (when `strict` and the lead has no "Medical spa" in `categories` but would have been kept through `ON_ICP_NAME`, return `"low_yield_category"`); `run_clean` passes `setting("clean_category_strict")`.
- [ ] Failing tests: `test_strict_rejects_name_only_med_spa_with_new_reason`; `test_strict_keeps_medical_spa_category`; `test_default_is_unchanged`; `test_run_clean_reads_the_setting` (monkeypatched `setting`). Implement. Run `tests/test_clean.py`, expect PASS. Commit `clean: strict Medical spa category`.

### Task 4: Yield report
**Files:** Create `scripts/yield_report.py`; Test `tests/test_yield_report.py` (pure helpers only).
**Interfaces:** Produces `summarise(leads: list[dict], cost_rows: list[dict], jobs: list[dict]) -> dict` (pure) and `main()` printing: per state `kept, enriched, rate`; per scrape run `scraped, kept, named, enriched`; per autopilot run window (successive `autopilot_started_at` values from the settings history are not stored, so use `walk` jobs grouped by day when a run list is unavailable: state this in the output) `enriched, usd, enriched_per_usd` (division guarded).
- [ ] Failing tests: `test_summarise_counts_and_guards_zero_division`. Implement; run once read-only against the real database and attach the output to the report. Commit `scripts: yield report`.

### Task 5: Docs and verification
- [ ] `CLAUDE.md` Commands: the two settings and `uv run python scripts/yield_report.py`; `docs/HANDOFF.md` section 0 line.
- [ ] Full suite once under the lock; one fresh whole-branch review on the most capable model; merge; push needs the owner's yes; deploy needs the owner's yes (queue idle).
- **Owner gates:** push, deploy, and judging the first run: the first autopilot run after deploy uses both settings on; the report compares it with the 2026-11-25 baseline (about 5 enriched for $2.40).

## Self-review
Coverage: settings (1), tile order and exploration (2), category filter (3), measurement (4), rollout and gates (5). Names consistent: `walk_yield_order`, `clean_category_strict`, `tile_scores`, `load_yield_stats`, `low_yield_category`.
