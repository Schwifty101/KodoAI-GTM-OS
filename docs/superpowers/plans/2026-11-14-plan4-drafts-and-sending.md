# Plan 4: Drafts and Sending Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drafts live in the database, the owner reviews a sample and approves in bulk on a Drafts page, and a VM scheduler sends approved drafts inside the ramp, window and pause rules from a Send page.

**Architecture:** The UI only reads/writes Postgres and enqueues jobs. Python passes (`check-drafts`, `redraft`) run as worker jobs through the existing CLI route (`gtm/worker.py` runs `gtm.cli <kind>`). Sending is a `send_tick` that runs on its own thread inside the worker (never queued behind a long job), claims a touch (`scheduled` -> `sending`) before the Gmail call, and sends from stored text.

**Tech Stack:** Python 3.14 (uv, pytest), Supabase Postgres, Next.js 16 under `web/` (read `web/node_modules/next/dist/docs/` first: this is not the Next.js you know), `web/lib/actions.ts` for every write.

**Spec:** `docs/superpowers/specs/2026-11-14-plan4-drafts-and-sending-design.md` (read it and section 9 of `2026-11-12-gtm-os-operating-layer-design.md`).

## Global Constraints

- `CLAUDE.md` rules: Postgres is the only database; only `gtm/config.py` reads the environment; suppression and already-contacted checked before every draft AND at send time; every paid call writes `cost_log`; no keys printed or committed; footer values empty by default, appended only if set; send is never part of draft.
- Sending limits (owner 2026-11-14): start 20, +3 a day, cap 40 per mailbox, auto-pause at 3% bounce over 20 sends (7-day window), Mon-Fri 9:00-16:00 in the lead's local time (null tz = America/Chicago), cadence Day 0/3/7, no Touch 4, plain text.
- Touch statuses: `drafted` (ready, awaiting approval), `held` (failed checks), `edited` (saved from the UI, awaiting re-check), `approved`, `scheduled`, `sending`, `sent`, `cancelled`.
- Test runs: `mkdir /tmp/gtm-pytest.lock` before pytest, `rmdir` after; one pytest process at a time (db tests share rows and clean up `TEST_%` leads). Manual or acceptance rows use the prefix `REHEARSAL_`, never `TEST_`. Apply a migration only with the owner's yes.
- Python style: ponytail (shortest working diff, no speculative abstractions). Each code task commits on its own.

## Review Focus

1. The owner edits a draft that is already `scheduled`/`sending`/`sent`: the edit must be refused, never change a claimed touch (Task 8 test, Task 9 verify).
2. Two senders at once (worker thread and terminal `send --confirm`): a touch is sent once (Task 7 claim test).
3. A lead replies, bounces or is suppressed after approval but before send: the tick cancels instead of sending (Task 7 test).
4. `send_at` outside the window, a null time zone, a DST boundary or the 16:00 edge: never sends outside Mon-Fri 9:00-16:00 local (Task 6 tests).
5. Empty states: a batch with zero ready drafts, an empty regenerate instruction, a model that returns an empty body: no crash, nothing approvable (Task 2, Task 10).

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0013_plan4_drafts_sending.sql` | new columns |
| `gtm/settings_store.py`, `web/lib/settings.ts` | `sending_on` setting |
| `gtm/draft.py` | store drafts in DB (no Gmail), held drafts, `instruction`, followups without Gmail |
| `gtm/draftcheck.py` (new) | `run_check_drafts`: re-check edited touches |
| `gtm/redraft.py` (new) | `run_redraft`: regenerate a batch with an instruction |
| `gtm/send.py` | ramp by sending days, `schedule_approved`, `send_scheduled`, `send_tick` |
| `gtm/worker.py`, `gtm/cli.py` | new job kinds, send-tick thread, `send` wrapper |
| `web/lib/actions.ts`, `web/lib/types.ts` | new writes and types |
| `web/app/drafts/page.tsx`, `web/app/send/page.tsx`, `web/app/layout.tsx` | the two pages and nav |
| `CLAUDE.md`, `docs/HANDOFF.md` | docs |

Parallel groups after Task 1: **A** (Tasks 2-4, drafts), **B** (Tasks 5-8, sending), **C** (Tasks 9-11, web). A and B both touch `gtm/cli.py` in one small step each: merge them in order A then B. Task 12 is last.

---

### Task 1: Migration and settings

**Files:** Create `supabase/migrations/0013_plan4_drafts_sending.sql`. Modify `gtm/settings_store.py`, `web/lib/settings.ts`. Test `tests/test_settings_store.py`.

**Interfaces:** Produces `touches.send_at timestamptz`, `touches.approved_at timestamptz`, `touches.problems text[] not null default '{}'`; `batches.draft_instruction text`; `mailboxes.ramp_from date`, `mailboxes.replies_checked_at timestamptz`; setting `sending_on: bool` default `False`.

- [ ] **Step 1: Failing test** in `tests/test_settings_store.py`: `test_sending_on_defaults_false` asserting `DEFAULTS["sending_on"] is False` and `all_settings`-style read returns `False`.
- [ ] **Step 2:** run `uv run pytest -q tests/test_settings_store.py` (lock first); expect FAIL (KeyError).
- [ ] **Step 3:** add `"sending_on": False` to `DEFAULTS`; add a mirrored `{ key: "sending_on", label: "Sending on", type: "bool", group: "Sending", def: false }` to `SETTING_FIELDS`. Write the migration with the five `alter table ... add column` statements (use `if not exists`).
- [ ] **Step 4:** tests pass; `cd web && node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts` ends `all ok` (it compares the two defaults).
- [ ] **Step 5:** ask the owner for a yes, apply the migration to project `alvxsbnfthvaiquhytig` (Supabase MCP `apply_migration`), then commit.

---

### Task 2 (group A): Drafts stored in the database, held drafts, instruction

**Files:** Modify `gtm/draft.py`, `gtm/cli.py` (the `draft` and `followups` commands). Test `tests/test_draft.py`.

**Interfaces:**
- Produces `draft_touch1(llm, lead: dict, attempts: int = 3, instruction: str | None = None) -> dict` returning `{"subject","body","objective","problems": list[str]}` for the LAST attempt, `problems == []` when clean (replaces the old `None`/`why` contract; the `why` param is removed). A missing field from the model becomes `""` and adds `bad_subject`/`no_objective`/an empty-body problem.
- Produces `_store(db, lead: dict, mailbox_id: str, touch_no: int, subject: str, body: str, objective: str, today: date, status: str = "drafted", problems: list[str] | None = None) -> None` inserting a `touches` row with NO Gmail call (`gmail_draft_id` and `gmail_thread_id` null).
- `run_draft(db, llm, batch_id: str, today: date, only_mailboxes: set[str] | None = None) -> int` (the `gmail_for` parameter is removed). Clean draft -> touch `drafted`; failed draft -> touch `held` with `problems`; lead becomes `drafted` either way.
- `run_followups(db, today: date) -> int` (no `gmail_for`, no `thread_messages`): inserts Touch 2/3 as `drafted` with the `Re:` subject and the Touch 1 `gmail_thread_id`; the `In-Reply-To` id is resolved at send time (Task 7).

- [ ] **Step 1: Failing tests** in `tests/test_draft.py`: `test_failed_draft_is_stored_held_with_problems` (fake llm returns a bad body 3 times; assert a `held` touch with non-empty `problems` and no `gmail_draft_id`); `test_clean_draft_is_stored_without_gmail` (fake gmail that raises if called; assert touch `drafted`); `test_instruction_reaches_the_prompt` (llm records its prompt; `instruction="warmer opener"` appears in it); `test_empty_model_answer_is_held_not_a_crash`; `test_followup_needs_no_gmail`.
- [ ] **Step 2:** run `tests/test_draft.py`; expect FAIL.
- [ ] **Step 3:** implement the signatures above in `gtm/draft.py` (the `instruction` is appended to `_prompt` as "Owner instruction for this batch: ..."); update the `draft`/`followups` commands in `gtm/cli.py` to the new signatures; remove the now-dead `create_draft` import. Port the existing `test_draft.py` cases that still apply (mechanical checks, skip printing becomes held rows).
- [ ] **Step 4:** `tests/test_draft.py` and `tests/test_cli.py` pass.
- [ ] **Step 5:** commit.

---

### Task 3 (group A): `check_drafts` pass

**Files:** Create `gtm/draftcheck.py`. Modify `gtm/cli.py` (new `check-drafts` subcommand), `gtm/worker.py` (add `"check-drafts"` to `ALLOWED`). Test `tests/test_draftcheck.py`.

**Interfaces:** Produces `run_check_drafts(db) -> int`: for every touch with `status = "edited"`, run `check_draft(body, touch_no)` plus the subject rule (`^.+ / .+$` for Touch 1), then set `status = "drafted"` with `problems = []` when clean, else `"held"` with the problem codes; returns the number re-checked.

- [ ] **Step 1: Failing tests:** `test_edited_clean_touch_becomes_drafted`, `test_edited_failing_touch_becomes_held_with_codes`, `test_non_edited_touches_are_untouched`, `test_edited_follow_up_is_checked_as_touch_2` (using `check_draft(..., 2)`), each on its own `REHEARSAL_` rows (create and delete them in the test).
- [ ] **Step 2:** run; expect FAIL (module missing).
- [ ] **Step 3:** implement; register the subcommand and the worker kind.
- [ ] **Step 4:** tests pass. **Step 5:** commit.

---

### Task 4 (group A): `redraft` pass

**Files:** Create `gtm/redraft.py`. Modify `gtm/cli.py` (`redraft --batch ID --instruction TEXT`), `gtm/worker.py` (`"redraft"` in `ALLOWED`). Test `tests/test_redraft.py`.

**Interfaces:** Consumes `draft_touch1(llm, lead, instruction=...)` from Task 2. Produces `run_redraft(db, llm, batch_id: str, instruction: str, today: date) -> int`: refuses an empty/whitespace instruction (`ValueError`); for every Touch 1 in the batch with status in (`drafted`, `held`, `edited`) it redrafts with the instruction, replaces the row's subject/body/objective/problems and status (`drafted` or `held`), clears `approved_at`; touches that are `approved`, `scheduled`, `sending`, `sent` are left alone; stores the instruction in `batches.draft_instruction`; each LLM call runs inside `spend_context(batch_id=..., lead_id=...)`.

- [ ] **Step 1: Failing tests:** `test_redraft_replaces_unsent_drafts_and_records_instruction`, `test_redraft_leaves_approved_and_sent_alone`, `test_empty_instruction_is_refused`, `test_redraft_failure_marks_held_not_lost` (llm raises for one lead: that touch keeps its old text and gets `problems=["redraft_failed"]`).
- [ ] **Step 2:** run; expect FAIL. **Step 3:** implement and register. **Step 4:** pass. **Step 5:** commit.

---

### Task 5 (group B): Ramp counts sending days

**Files:** Modify `gtm/send.py`. Test `tests/test_send.py`.

**Interfaces:** Produces `is_test_lead(place_id: str) -> bool` (prefixes `TEST_`, `REHEARSAL_`); `sending_days(db, mailbox_id: str, before: date) -> int`: count of distinct UTC dates before `before`, on or after the mailbox's `ramp_from` (if set), on which that mailbox sent at least one touch to a non-test lead; `allowance(mailbox: dict, days_sent: int, ramp_start: int, ramp_step: int, cap: int) -> int` = `min(cap, ramp_start + ramp_step * days_sent)`, 0 if `enabled_on` is null or the mailbox is paused.

- [ ] **Step 1: Failing tests:** `test_first_real_send_day_allows_ramp_start` (no earlier sends -> 20), `test_second_sending_day_allows_23`, `test_a_gap_day_does_not_advance_the_ramp`, `test_rehearsal_sends_do_not_advance_the_ramp`, `test_ramp_restarts_after_ramp_from`, `test_cap_holds_at_40`, `test_is_test_lead_prefixes`.
- [ ] **Step 2:** run `tests/test_send.py -k "ramp or allowance or is_test"`; expect FAIL. **Step 3:** implement. (The restart-after-pause rule lives in `ramp_from`: Python never writes it; the web `clearPause` in Task 9 sets it to today when the owner unpauses.) **Step 4:** pass. **Step 5:** commit.

---

### Task 6 (group B): Scheduling approved touches

**Files:** Modify `gtm/send.py`. Test `tests/test_send.py`.

**Interfaces:** Produces `schedule_approved(db, mailbox: dict, now: datetime, settings: Settings, rng: random.Random | None = None, anytime: bool = False) -> int`: for the mailbox's `approved` touches (Touch 2/3 first, then Touch 1 by `approved_at`) whose lead is not stopped/blocked, assign `status = "scheduled"` and a random `send_at` in `[now, window_end)` of the lead's local day, only while `room > 0` where `room = allowance(...) - (sent today + scheduled + sending)`; a lead outside its window now stays `approved` (it is picked up on a later tick); returns the number scheduled. Reuses `in_window(now, tz)`; add `window_end(now: datetime, tz: str | None) -> datetime`.

- [ ] **Step 1: Failing tests:** `test_follow_ups_are_scheduled_before_new_leads`, `test_scheduling_stops_at_the_allowance`, `test_every_send_at_is_inside_the_leads_window` (property over 50 random seeds, including tz `None`, `America/Los_Angeles`, and a DST-boundary date), `test_outside_window_stays_approved`, `test_sixteen_oclock_edge_is_excluded`, `test_stranded_sending_counts_against_room`.
- [ ] **Step 2:** run; FAIL. **Step 3:** implement. **Step 4:** pass. **Step 5:** commit.

---

### Task 7 (group B): Claim and send

**Files:** Modify `gtm/send.py`. Test `tests/test_send.py` (fake gmail).

**Interfaces:** Consumes `create_draft`, `send_draft`, `thread_messages` from `gtm/gmail.py`. Produces `send_scheduled(db, gmail_for, mailbox: dict, now: datetime, settings: Settings, anytime: bool = False) -> dict[str, int]`: for `scheduled` touches with `send_at <= now` (and in window unless `anytime`): re-check stopped status and `blocked_reason` (cancel a blocked or stopped touch, count `cancelled`); claim atomically with `update touches set status='sending' where id=? and status='scheduled'` (skip when zero rows come back); for Touch 2/3 resolve the first `message-id` header from the Touch 1 thread; `create_draft(...)` then `send_draft(...)`; on success `status='sent'`, `sent_at=now`, `gmail_thread_id` set, and for Touch 1 the lead becomes `sent`. A failure in `create_draft` reverts the claim to `scheduled` (count `errors`); a failure in `send_draft` leaves `sending` (ambiguous, counted `stranded`) and is never retried automatically.

- [ ] **Step 1: Failing tests:** `test_send_once_under_two_concurrent_claims` (two calls, one fake gmail: exactly one `send_draft`), `test_reply_after_approval_cancels_not_sends` (lead `replied`), `test_suppressed_lead_is_cancelled`, `test_create_draft_failure_reverts_to_scheduled`, `test_send_draft_failure_leaves_sending_and_is_not_retried`, `test_touch_2_uses_in_reply_to_and_thread` (fake gmail records `thread_id` and `in_reply_to`), `test_touch_1_marks_lead_sent`.
- [ ] **Step 2:** run; FAIL. **Step 3:** implement. **Step 4:** pass. **Step 5:** commit.

---

### Task 8 (group B): The tick, auto-pause, worker thread, CLI wrapper

**Files:** Modify `gtm/send.py`, `gtm/worker.py`, `gtm/cli.py` (the `send` command), `gtm/replies.py` only if needed. Test `tests/test_send.py`, `tests/test_worker.py`, `tests/test_cli.py`.

**Interfaces:** Produces `send_tick(db, gmail_for, llm, now: datetime | None = None, settings: Settings | None = None, force: bool = False, anytime: bool = False) -> dict`: returns `{"off": 1}` and does nothing unless `setting("sending_on")` or `force`; otherwise, per unpaused mailbox: auto-pause check (existing `should_pause` rule, 3% over 20, 7 days, sets `paused` and `paused_reason`), `run_replies`, stamp `mailboxes.replies_checked_at = now`, `schedule_approved`, `send_scheduled`; replaces `send_due` and `send_with_reply_check` (delete both). Produces `worker.send_loop(every: float = 60.0)` started as a daemon thread in `worker.main` with its OWN `get_db()` client; an exception is printed, never fatal. The terminal `send --confirm [--anytime]` calls `send_tick(..., force=True, anytime=a.anytime)`; the dry run prints the same per-mailbox allowance line as today and still exits without writing. Remove the `send is not job-runnable` comment on `ALLOWED`.

- [ ] **Step 1: Failing tests:** `test_tick_does_nothing_when_sending_off`, `test_tick_does_nothing_when_mailbox_paused`, `test_tick_reads_replies_before_sending`, `test_bounce_spike_auto_pauses_and_sends_nothing`, `test_force_sends_even_when_off` (CLI path), `test_worker_main_starts_the_send_loop_thread` (patch `threading.Thread`), `test_send_loop_survives_an_exception`, `test_cmd_send_dry_run_writes_nothing`.
- [ ] **Step 2:** run; FAIL. **Step 3:** implement. Port every `send_due` test that still applies (stopped-lead cancellation, suppression, held duplicate, bounce pause) to the new functions, then delete `send_due`. **Step 4:** `tests/test_send.py tests/test_worker.py tests/test_cli.py` pass. **Step 5:** commit.

---

### Task 9 (group C): Web actions and types

**Files:** Modify `web/lib/actions.ts`, `web/lib/types.ts`, `web/scripts/verify.mts`.

**Interfaces:** Produces (each via the existing `ok(...)` helper; every update filters on the current status so a claimed touch is never changed): `saveDraftEdit(touchId, subject, body)` (sets `edited` only where status in `drafted|held|edited|approved`, clears `approved_at`), `approveTouches(ids)` (`drafted` -> `approved`, sets `approved_at`), `unapproveTouches(ids)`, `skipTouch(id)` (`drafted|held|approved` -> `cancelled`), `markSent(id)` and `markFailed(id)` (only from `sending`; failed -> `approved`), `startSending()` and `pauseSending()` (`saveSetting("sending_on", true|false)`), `redraftBatch(batchId, instruction)` (refuses empty; `enqueueJobOnce("redraft", ["--batch", id, "--instruction", text])`), `checkDrafts()` (`enqueueJobOnce("check-drafts", [])`). Change `clearPause` to also set `ramp_from` to today. Types: `Touch` with the new columns and `TouchStatus` union.

- [ ] **Step 1:** add `verify.mts` checks on `REHEARSAL_` rows: `edit refuses a scheduled touch`, `edit clears approval`, `approve only moves drafted`, `markFailed only from sending`, `redraft refuses empty instruction`, `clearPause sets ramp_from`.
- [ ] **Step 2:** run the `verify.mts` command; expect the new checks to FAIL (functions missing). **Step 3:** implement. **Step 4:** `all ok`. **Step 5:** commit.

---

### Task 10 (group C): `/drafts` page (sample-first)

**Files:** Create `web/app/drafts/page.tsx`. Modify `web/app/layout.tsx` (nav link "Drafts").

**Interfaces:** Consumes Task 9 actions. Behaviour (spec section 5.1, mockup option A): batch picker; counts (total, ready, held); a sample of 10 random `drafted` Touch 1 (shuffled once per load; fewer if fewer exist) shown one at a time with **Looks good**, **Edit** (inline subject/body, saves via `saveDraftEdit` then `checkDrafts`), **Flag a problem**; angle shown beside each draft; held drafts listed with their `problems`, plus leads the draft pass skipped as already contacted or suppressed (they stay `selected` with `leads.reject_reason`; show that reason under Held, never approvable); **Approve all ready** (disabled at zero) and **Regenerate batch with a new instruction** (textarea, disabled when empty) visible from the start; an edited draft shows "checking..." until its status leaves `edited`.

- [ ] **Step 1:** create `REHEARSAL_` leads and touches (a script in `$CLAUDE_JOB_DIR/tmp`) covering ready, held, edited and an empty batch.
- [ ] **Step 2:** implement the page following `web/app/review/page.tsx` (client component, `useRequireSession`, `supabase` reads).
- [ ] **Step 3:** run `cd web && npm run dev`, open the page in a real browser (claude-in-chrome or Playwright) and check: sample renders, Edit saves and shows "checking...", Approve all moves only ready rows, Regenerate refuses empty text, an empty batch shows no crash. Record a screenshot path in the commit message body.
- [ ] **Step 4:** `npx tsc --noEmit` clean. **Step 5:** commit.

---

### Task 11 (group C): `/send` page (Today and Follow-ups tabs)

**Files:** Create `web/app/send/page.tsx`. Modify `web/app/layout.tsx` (nav link "Send").

**Interfaces:** Behaviour (spec sections 5.2, 5.3, mockup option B). **Today:** mailbox, allowance today, sent today, bounce rate over 7 days, `sending_on` state with **Start sending** / **Pause**, the pause reason when set (with `clearPause`), queue counts (scheduled, next `send_at`, approved-but-unscheduled, held), and stranded `sending` touches with **Mark sent** / **Mark failed**. **Follow-ups:** Touch 2/3 `drafted` rows with the Touch 1 subject and body, follow-up text, days since Touch 1, outcome, the mailbox's `replies_checked_at`, planned slot if scheduled, overdue badge, **Approve**, **Approve all**, **Edit**, **Skip**; the tab shows a count badge. Allowance on the page is computed from the same rule as Python: `min(40, 20 + 3 * days_sent)`; if a duplicate TypeScript formula is judged worth avoiding, read it from a `mailboxes` view instead (builder's call, note it in the commit).

- [ ] **Step 1:** seed `REHEARSAL_` rows for each state (scheduled, stranded `sending`, pending and overdue follow-ups, a paused mailbox copy is NOT created: use the real mailbox read-only).
- [ ] **Step 2:** implement. **Step 3:** browser check: tabs and badge, Start/Pause toggle the setting, Approve moves a follow-up, Mark failed returns a stranded touch to `approved`, no page error. **Step 4:** `npx tsc --noEmit` clean. **Step 5:** commit.

---

### Task 12: Docs, full suite, and the live acceptance

**Files:** Modify `CLAUDE.md`, `docs/HANDOFF.md`.

- [ ] **Step 1:** update `CLAUDE.md`: the UI now has Drafts and Send pages with a Start sending control; the Gmail draft is no longer the source of truth; sending is job-driven (`send_tick` on the worker) and the terminal `send --confirm` is the same code; the `send is not job-runnable` and "edit drafts in Gmail" lines are removed. Update `docs/HANDOFF.md` section 0 (Plan 4 built, what is verified).
- [ ] **Step 2:** full suite under the lock (`uv run pytest -q`, about 9 minutes) all green; `verify.mts` `all ok`; `verify_scrape.mts` and `verify_batches.mts` still ok.
- [ ] **Step 3 (with the owner, no real leads):** rehearsal to `sobanahmad2003+...@gmail.com` with `REHEARSAL_` leads: draft, sample-review in the browser, approve, Start sending (use `--anytime` only for the first terminal run; the scheduler run is checked on a weekday inside the window), a reply stops the sequence, a bounce is recorded, Touch 2 and Touch 3 appear on Follow-ups and thread correctly. Clean up all rehearsal rows and suppression rows afterwards.
- [ ] **Step 4:** deploy only when the queue is idle (`bash deploy/deploy.sh gtm-worker us-west1-b`), then repeat a short rehearsal with the scheduler running on the VM; check `systemctl` memory (`free -m`) during a tick and record the peak in `docs/HANDOFF.md`.
- [ ] **Step 5:** commit and open the PR. The first real send of the 8 Houston leads happens only after this, with the owner approving each step; no manual `mailboxes.enabled_on` change is needed any more (the ramp counts sending days).
