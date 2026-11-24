# Plan 8 design: UI run-now actions and Preview/Apply

Date 2026-11-24. Owner-approved scope: preview first, then apply. UI and a thin guard only; no worker or Python change.

## Problem
Every sheet and batch step is CLI-only today. The owner wants to run them from the OS, but a one-click paid or sheet-writing action is unsafe. The sheet passes already have a CLI dry run (`--confirm` writes); the UI must use it.

## Mechanism
- The UI never runs anything itself. It inserts a `jobs` row (existing `enqueueJob`, `enqueueJobOnce` in `web/lib/actions.ts`); the VM worker runs it (all kinds are already in `gtm/worker.py` ALLOWED).
- **Preview** enqueues `argv`; the component polls that jobs row and shows `result.output` (worker stores the last 4000 chars).
- **Apply** enqueues `argv + ["--confirm"]`. It is disabled until a `done` preview job exists for the same kind and the same argv (created within the last 24 h, so a stale preview does not unlock it).
- One shared `PreviewApply` component and one server-side-style guard `enqueueApply(kind, argv)` in `web/lib/actions.ts`. The guard re-checks the done preview in the database and refuses otherwise, so a hand-built call cannot skip it.

## Passes and what Preview means
| Kind | Preview | Apply |
|---|---|---|
| import-sheet, sheet-queue, sheet-paint | real CLI dry run (no `--confirm`) | `--confirm` |
| verify-sheet `--batch ID` | real CLI dry run; output shows email count; costs 0.5 Hunter credit per email on Apply | `--confirm` |
| enrich `--batch ID` | none exists. UI estimate: count of `cleaned` leads in the batch times the credit cost, then a typed-count confirm. No Preview job | plain run after confirm |
| clean, signals, select, draft, followups | none exist (no `--confirm` flag, they act directly). Single Run button with a confirm dialog that names the batch and the lead count | plain run |

The guard therefore applies only to `--confirm`-bearing kinds (import-sheet, verify-sheet, sheet-queue, sheet-paint). Adding a `--confirm` to the other passes is out of scope.

## Screens
1. **Settings, "Sheet" block**: Import now, Run queue now, Paint colours now (each PreviewApply); the `sheet_queue_on` and `sheet_writeback_on` switches grouped with them; one last-run line per kind from `jobs` (status, time, first output line). Paint Apply also needs `sheet_writeback_on` on, else disabled with the reason.
2. **/batches per-batch action row** (rows of the scrape/import batches table, keyed by `batches.id`): clean, verify-sheet, enrich, signals, select. Order: import, clean, verify-sheet, enrich, signals, select. A step is greyed out until the previous step has a `done` job for that `--batch`; the reason shows on hover. Import counts as done when the batch is a sheet import.
3. **/drafts**: Draft button for the batch (`draft --batch ID`, via enqueueJobOnce). **/send**: Draft follow-ups button (`followups`, via enqueueJobOnce).
4. **Settings Jobs dropdown** keeps working. Missing kinds (import-sheet, verify-sheet, sheet-queue, sheet-paint) are added; for those, a `--confirm` in the argv is rejected by the same guard unless a done preview exists.

## Stays CLI-only
scrape by city, seed-coverage, tz-backfill, import-history, mailbox add, sheet-format, deploy, send `--anytime`.

## Hard gates (never done by the implementing agent without the owner)
- Any write to the real sheet (Apply of import-sheet writes leads only, but sheet-queue and sheet-paint write the sheet; first paint and first Queue write are already hard gates). Rehearse with `--sheet-id COPY`, dry run only for import.
- Any paid call: verify-sheet Apply, enrich, signals, draft, redraft.
- Deploys: the worker needs no change; the UI is local. No VM deploy for this plan.
- Tests and verify scripts use `TEST_` place ids and `TEST` batch names only and never touch real batches, real settings values (restore after) or the real queue.

## Dependency on Plan 7
Plan 7 (`2026-11-24-plan7-os-status-design.md`, other author) changes `gtm/sheet*.py` and the `sheet-paint` output (os_status column, paint added to the daily schedule). Plan 8's paint button depends on it only for the preview text, not for code: it shows whatever the dry run prints.

## Testing
Pure logic (guard, step ordering, last-run, estimate) is unit-tested with `node --test`-style tsx scripts; DB behaviour with a `web/scripts/verify_runnow.mts` under RLS; the UI with a real browser run (login by magic link, Preview on a test job, Apply disabled then enabled). Jobs for tests use kind `import-sheet_test`-style test kinds the live worker never claims (migration 0011 `include_test`).

## Out of scope
Auto-chaining steps, scheduling, new CLI flags, a dry run for clean/enrich/signals/select/draft, metrics (Plan 6).
