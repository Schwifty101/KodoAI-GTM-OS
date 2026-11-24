# Plan 8: UI run-now actions and Preview/Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run the sheet and batch steps from the UI, preview first, apply second, through the existing jobs queue.

**Architecture:** One pure-logic module `web/lib/runnow.ts` (guard, ordering, last-run, estimate) and one component `web/components/PreviewApply.tsx`, wired into four pages. The worker is unchanged: all kinds are in `gtm/worker.py` ALLOWED.

**Tech Stack:** Next.js, TypeScript, Supabase RLS, tsx scripts.

**Spec:** `docs/superpowers/specs/2026-11-24-plan8-ui-run-now-design.md`

## Global Constraints
- Docs-style rules: no emojis, no invented numbers. Every UI write goes through `web/lib/actions.ts` (so verify scripts hit the same code).
- Preview = enqueue argv without `--confirm`; Apply = argv + `["--confirm"]`; Apply needs a `done` preview job, same kind and same argv, created in the last 24 h.
- Real CLI dry runs exist only for import-sheet, verify-sheet, sheet-queue, sheet-paint. clean, signals, select, draft, followups have no `--confirm` and no dry run (checked in `gtm/cli.py`): they get a confirm dialog, not a Preview. enrich gets a UI estimate.
- Tests and verify scripts: `TEST_` place ids, batch names starting `TEST`, test job kinds ending `_test` (live worker never claims them, migration 0011). Never real batches, never the real sheet, never paid calls.
- Run one pytest or verify process at a time. Do not commit unless the executor is told to; do not touch the untracked Codex files.

## Review Focus
- Double click on Preview: second click must be refused by `enqueueJobOnce`, not create two jobs.
- Preview job `failed` or `cancelled`: Apply stays disabled and the error shows.
- Argv differs by a flag or batch id between Preview and Apply: Apply disabled (exact JSON match).
- Preview older than 24 h: Apply disabled.
- `sheet_writeback_on` off: paint Apply disabled with the reason, Preview still works.

## Task groups (parallelisable)
Group A (sequential first): Task 1, Task 2. Then Group B in parallel (disjoint files): Tasks 3, 4, 5, 6. Then Group C: Task 7, Task 8.

### Task 1: Pure logic `web/lib/runnow.ts`
**Files:** Create `web/lib/runnow.ts`, `web/scripts/runnow_unit.mts`.
**Interfaces:** Produces
- `type JobRow = Pick<Job, "id"|"kind"|"status"|"payload"|"result"|"error"|"created_at"|"finished_at">` (reuse `Job` from `web/lib/types.ts`; add `result`/`error` there if missing).
- `const CONFIRM_KINDS = ["import-sheet","verify-sheet","sheet-queue","sheet-paint"]`
- `baseKind(kind: string): string` strips a trailing `_test`.
- `sameArgv(a: string[], b: string[]): boolean` (JSON equality).
- `findPreview(jobs: JobRow[], kind: string, argv: string[], now?: Date): JobRow | undefined` latest `done` job with same kind and argv (no `--confirm`), under 24 h old.
- `stepState(order: string[], step: string, jobs: JobRow[], batchId: string): {enabled: boolean; why?: string}` where order is `["import","clean","verify-sheet","enrich","signals","select"]` and a step is enabled when the previous step has a `done` job whose argv contains `batchId` (import is enabled if `isSheetImport`).
- `lastRun(jobs: JobRow[], kind: string): JobRow | undefined`.
- `enrichEstimate(cleaned: number, creditPerLead: number): {leads: number; credits: number}`.
- [ ] **Step 1:** In `runnow_unit.mts` write plain `assert` tests: `findPreview` returns undefined for a failed job, a different argv, a 25 h old job, and a job whose argv already has `--confirm`; returns the newest done one otherwise. `stepState` for `clean` is disabled with why `"import not done"` with no jobs and enabled after a done import job. `baseKind("verify-sheet_test") === "verify-sheet"`. `lastRun` picks the newest by `created_at`.
- [ ] **Step 2:** Run `cd web && npx tsx scripts/runnow_unit.mts`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement the signatures above in `runnow.ts`, pure functions, no Supabase import.
- [ ] **Step 4:** Rerun. Expected: all asserts pass, exit 0.
- [ ] **Step 5:** Commit `feat: runnow pure logic`.

### Task 2: Guard and server actions in `web/lib/actions.ts`
**Files:** Modify `web/lib/actions.ts`; Create `web/scripts/verify_runnow.mts`.
**Interfaces:** Consumes `findPreview`, `CONFIRM_KINDS`, `baseKind`. Produces
- `enqueuePreview(kind: string, argv: string[]): Promise<void>`: throws if `argv` contains `--confirm`; calls `enqueueJobOnce`.
- `enqueueApply(kind: string, argv: string[]): Promise<void>`: appends `--confirm`; selects recent jobs of that kind from `jobs`; throws `"no done preview for this argv"` when `findPreview` is empty; then `enqueueJobOnce(kind, [...argv, "--confirm"])`.
- `enqueueGuarded(kind: string, argv: string[])`: used by the Jobs dropdown: if `baseKind(kind)` is in `CONFIRM_KINDS` and argv contains `--confirm`, route to `enqueueApply` with the confirm stripped; otherwise `enqueueJobOnce`.
- [ ] **Step 1:** In `verify_runnow.mts` (copy header and login pattern of `web/scripts/verify_batches.mts`, TEST batch, admin cleanup in `finally`) assert under RLS, with kind `verify-sheet_test`: `enqueueApply` throws with no preview; after an admin-inserted `done` job with the same argv, `enqueueApply` inserts a queued job with `--confirm` last; with a different argv it throws; `enqueuePreview` twice throws the second time (identical job open); `enqueueGuarded("import-sheet_test", ["--confirm"])` throws.
- [ ] **Step 2:** Run `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_runnow.mts`. Expected: FAIL (exports missing).
- [ ] **Step 3:** Implement the three functions; no new table, no migration. Also fix the existing `enqueueJobOnce` race note only if the test shows a double insert (then add a unique partial index in a new migration and stop for owner approval: schema change gate).
- [ ] **Step 4:** Rerun. Expected: every line `ok`, no FAIL; test rows deleted.
- [ ] **Step 5:** Run `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts`. Expected: still passes (regression).
- [ ] **Step 6:** Commit `feat: preview/apply guard`.

### Task 3: `PreviewApply` component (Group B)
**Files:** Create `web/components/PreviewApply.tsx`.
**Interfaces:** Consumes `enqueuePreview`, `enqueueApply`, `findPreview`, `lastRun`. Produces
`<PreviewApply kind: string argv: string[] label: string cost?: string disabledReason?: string jobs?: JobRow[] />` (client component).
- [ ] **Step 1:** Behaviour: Preview button; after click, poll `jobs` for the newest row of `kind` with this argv every 3 s until status is `done`, `failed` or `cancelled`; show `result.output` in a `<pre>` (or the error). Apply button: disabled unless `findPreview` is set and `disabledReason` is empty; label shows `cost` text (for example "0.5 Hunter credit per email"); a `window.confirm` names the label before enqueue. Show the disabled reason as text next to the button. Stop polling on unmount.
- [ ] **Step 2:** `cd web && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 3:** Commit `feat: PreviewApply component`.
(Behaviour is proven by Task 7 browser run; no jsdom dependency added.)

### Task 4: Settings "Sheet" block (Group B)
**Files:** Modify `web/app/settings/page.tsx`, `web/lib/settings.ts` only if the two switches are not already in `SETTING_FIELDS`.
- [ ] **Step 1:** Add a "Sheet" section above Jobs: three `PreviewApply` (`import-sheet []`, `sheet-queue []`, `sheet-paint []`), the `sheet_queue_on` and `sheet_writeback_on` switches rendered with the existing `SettingInput`, and a last-run line per kind from the already-loaded `jobs` state via `lastRun` (status, time, first output line). Paint gets `disabledReason="turn on sheet_writeback_on"` when it is off.
- [ ] **Step 2:** In the Jobs dropdown: extend `JOB_KINDS` with `import-sheet, verify-sheet, sheet-queue, sheet-paint`; replace `enqueueJob(kind, ...)` with `enqueueGuarded`.
- [ ] **Step 3:** `cd web && npx tsc --noEmit`; `node --env-file=.env.local --env-file=../.env --import tsx scripts/settings_groups.mts`. Expected: pass.
- [ ] **Step 4:** Commit `feat: settings sheet block`.

### Task 5: /batches outreach cards and intake action row (Group B)
**Files:** Modify `web/app/batches/page.tsx`, `web/lib/batches.ts`.
**Interfaces:** Produces in `batches.ts`: `loadBatchJobs(): Promise<JobRow[]>` (jobs of kinds clean, verify-sheet, enrich, signals, select, import-sheet, last 200) and `countCleaned(batchId: string): Promise<number>`.
- [ ] **Step 0:** Outreach cards at the top: `loadOutreachBatches(): Promise<{batch_no: number; leads: number; selected: number; approved: number; drafted: number; sent: number; replied: number}[]>` grouped from `leads.batch_no` (non-null), shown as "Batch 03: 28 of 100". Intake section below, collapsed by default, rows labelled by created date and name, never the id.
- [ ] **Step 1:** Per-intake-run row (the scrape/import batches table, key `batches.id`, id never shown): clean (confirm dialog, `enqueueJobOnce("clean",["--batch",id])`), verify-sheet (`PreviewApply`, cost "0.5 Hunter credit per email"), enrich (estimate: `countCleaned` times the Hunter/Prospeo credit per lead from `docs/spikes/owner_routes.md`, read that number there, do not invent it; confirm step requires typing the lead count), signals, select (confirm dialog). Each step uses `stepState`; greyed with the reason as title text.
- [ ] **Step 2:** Add to `verify_batches.mts` a check for `loadBatchJobs` and `countCleaned` on the TEST batch (kind `enrich_test`, as that script already does).
- [ ] **Step 3:** Run `node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_batches.mts`. Expected: all ok.
- [ ] **Step 4:** Commit `feat: batches action row`.

### Task 6: /drafts Draft per outreach batch and /send Draft follow-ups (Group B)
**Files:** Modify `gtm/cli.py`, `gtm/draft.py`, `tests/test_draft.py`, `web/app/drafts/page.tsx`, `web/app/send/page.tsx`, `web/lib/actions.ts` (two one-line exports).
**Interfaces:** Produces `run_draft(db, llm, batch_id: str | None, today: date, only_mailboxes: set[str] | None = None, batch_no: int | None = None) -> int` (exactly one of `batch_id`, `batch_no`; `batch_no` selects `status=selected, approved=true, batch_no=N` across source batches) and CLI `draft --batch-no N` (argparse mutually exclusive with `--batch`, one required).
- [ ] **Step 0 (Python, TDD):** failing test `test_draft_by_batch_no_takes_approved_selected_leads_across_source_batches` (`TEST_` leads in two `TEST` batches, same `batch_no`, one unapproved: only the approved two drafted; both args or neither raises). Implement, run `tests/test_draft.py` under the lock.
- [ ] **Step 1:** `draftBatch = (batchNo: number) => enqueueJobOnce("draft", ["--batch-no", String(batchNo)])`, `draftFollowups = () => enqueueJobOnce("followups", [])`.
- [ ] **Step 2:** Buttons with a confirm dialog (drafts are paid LLM calls on paid Gemini only if `allow_paid_gemini` is on; say so). Show "already queued" on the open-job error.
- [ ] **Step 3:** Add two asserts to `verify_runnow.mts` using kinds `draft_test` and `followups_test` (open-job duplicate refused). Rerun Task 2 step 2 command. Expected: ok.
- [ ] **Step 4:** Commit `feat: draft buttons`.

### Task 7: Real browser verification (Group C, owner present for login)
- [ ] **Step 1:** `cd web && npm run dev`; log in with the magic link. Using the Claude-in-Chrome or Playwright tools. Apply cannot be exercised on real kinds, so drive the component with a test page route `web/app/_verify/page.tsx` (delete after) that renders `<PreviewApply kind="verify-sheet_test" argv={["--batch","TEST"]} />`.
- [ ] **Step 2:** Check, with screenshots: Apply disabled at first; click Preview, admin marks the queued job `done` with output text; output appears; Apply enabled; change argv, Apply disabled; mark a second preview `failed`, Apply disabled with error. Check /batches greyed steps with a TEST batch, and that the Settings Jobs dropdown rejects `import-sheet --confirm` with no preview.
- [ ] **Step 3:** Delete the `_verify` route and all TEST rows. `git status` shows only Plan 8 files (and the untracked Codex files untouched).

### Task 8: Docs (Group C)
**Files:** Modify `CLAUDE.md` Commands section (one bullet on the UI run-now buttons and the guard), `docs/HANDOFF.md` section 0 status row.
- [ ] **Step 1:** Edit both; keep each to a few lines. Commit `docs: plan 8`.

## Hard gates (stop and ask the owner)
1. Any real Apply of import-sheet, sheet-queue or sheet-paint, and any run against the real `sheet_id`. Rehearse only on a copy with `--sheet-id COPY` (dry run for import).
2. Any paid call: verify-sheet Apply (Hunter), enrich, signals, draft, followups, redraft.
3. Any migration, VM deploy or `deploy.sh`. None is planned.
4. Any change to real settings values or real batches; test rows only.
5. Plan 7 landing first changes paint output only; no ordering constraint on code.

## Self-review
Spec coverage: shared component and guard (Tasks 1-3), Settings Sheet block (4), batches row (5), drafts and send buttons (6), Jobs dropdown guard (2, 4), browser and RLS checks (2, 5, 6, 7), CLI-only list untouched, Plan 7 note in the spec. Finding to relay: clean, signals, select, draft, followups have no dry run, so Preview/Apply there is replaced by a confirm dialog; owner may later ask for a `--confirm` flag on them.
