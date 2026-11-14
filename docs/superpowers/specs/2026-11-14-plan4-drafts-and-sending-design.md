# Plan 4 design: Drafts and Sending

Date: 2026-11-14. Status: **awaiting owner approval** (all builder questions settled; decision 7 added). Nothing here is built. It narrows sections 8, 9 and 15 of `2026-11-12-gtm-os-operating-layer-design.md` into one buildable plan and records what the owner decided in the 2026-11-14 brainstorm. Where this document and that one disagree, this one rules (known case: section 9 still says auto-pause at 5% over 40 sends; the rule is **3% over 20 sends**, owner 2026-11-14).

## 1. Intent and why

Today the owner reviews drafts in Gmail and sends from a terminal (`send --confirm`). Both steps are manual, one email at a time, and not fit for 100-lead batches and about 200 emails a week. The owner's old manual flow was: get an editable draft, tweak it in place, press Send. Plan 4 gives the OS the same loop at volume: read a sample, fix problems, approve the rest in bulk, press one Start button, and let the OS send inside safe limits while it keeps the memory (Day 3 and Day 7 follow-ups, replies, bounces, suppression) that the owner used to hold in a sheet.

The first live rehearsal (2026-11-14, to the owner's own Gmail) proved the existing passes work; it also exposed gaps (no send window, silent draft skips) that were fixed. Plan 4 builds the screens and the scheduler on top of those proven passes.

## 2. Goals, non-goals, anti-goals

**Goals**
- A **Drafts** page: sample-first review of a batch, edit in place, approve in bulk, regenerate the batch with a changed instruction.
- A **Send** page with two tabs, Today and Follow-ups: capacity, a Start sending button, pause, and Pending follow-ups approval.
- Drafts live in the database; the OS creates the Gmail draft and sends from stored text.
- A scheduler that runs on the VM worker, so sending does not need the owner's Mac awake.
- Every skipped or failed draft is visible and recoverable (closes the "silent skip" gap properly).

**Non-goals (explicitly later)**
- The integrated Gemini assistant window (owner: on hold).
- Gemini rewriting chosen drafts in bulk ("shorten the opener"); the owner chose regenerate-the-batch and manual edit instead.
- Positive-reply drafting; the Replies, Metrics and Home pages (Plans 5 and 6); sheet import and the manual queue (Plan 5).
- More than one mailbox; a Gmail App Script or any non-Gmail-API sender.

**Anti-goals (a failure even if it works)**
- Any email sent while sending is off (before Start or after Pause), a draft sent without approval, or a follow-up sent without its own approval.
- A draft edited by the owner that no longer passes the mechanical checks being approvable.
- Sending outside Mon-Fri 9:00-16:00 in the lead's local time, over the daily allowance, or to a suppressed or already-contacted address.
- The UI holding the Supabase secret key, or the Gmail token leaving the Mac and the VM.

## 3. Constraints

`CLAUDE.md` governs. In particular: Supabase Postgres is the only database; only `gtm/config.py` reads the environment; suppression and "already contacted" are checked before every draft **and** again at send time; every paid call writes `cost_log`; no keys printed or committed; the footer stays empty (do not fill it); emails stay plain text, short, no links, no tracking. Cadence is Day 0/3/7, no Touch 4. Sending limits (owner 2026-11-14): start 20 a day, +3 a day, cap 40 per mailbox, auto-pause at 3% bounce over 20 sends (7-day window). One mailbox, `soban@kodoai.xyz`. Gmail OAuth consent screen is Internal, so the token does not expire; the VM already loads the token from Secret Manager and a Gmail send from the VM was verified on 2026-11-14 (the OS passes themselves have not run there).

## 4. What the owner decided

1. **Review model:** read a sample, approve the rest in bulk.
2. **Fixing a bad batch:** regenerate the whole batch with a changed instruction, or edit manually. (No bulk Gemini rewrite in this plan.)
3. **Drafts page layout:** sample-first. It opens on about 10 random drafts shown one after another, each with Looks good, Edit and Flag a problem. **Approve and Regenerate are visible from the start**, not only after the sample.
4. **Send page layout:** two tabs, **Today** and **Follow-ups** (with a count badge).
5. **Editing happens in the OS.** The Gmail draft stops being the source of truth.
7. **Start sending turns sending ON** (owner 2026-11-14, after the builder review). It stays on across weekdays until the owner presses Pause or the approved queue is empty. While on, the scheduler also sends the overflow from a day that hit its allowance and anything the owner approves later (including a follow-up approved on a later day) without another Start click. The explicit acts are Start and each approval.
6. **Follow-ups** (section 9 of the earlier design, unchanged): Touch 2 and 3 are drafted automatically when due and wait on the Follow-ups tab for approval; each card shows the reply check, planned slot, and Approve, Edit, Skip; there is an "Approve all".

## 5. Behaviour

### 5.1 Drafts page
- A **batch** is shown with counts: total, ready (passed `check_draft`), held (failed). Held drafts show their failure reasons and are excluded from bulk approve.
- The **sample** is about 10 random ready drafts (my call: 10; configurable constant). The owner can still open any other draft.
- **Edit** saves subject and body to the database. After every save the mechanical checks run again; a draft that fails goes to held and cannot be approved until fixed.
- **Approve all ready** marks every ready draft approved. Per-draft Approve also exists.
- **Regenerate batch with a new instruction:** the owner types an instruction; every not-yet-sent draft in the batch is redrafted with that text added to the model prompt. Held and ready drafts are both redrafted; approved drafts are not touched unless the owner confirms. The instruction is stored on the batch for later reference. Gemini cost counts against the existing daily cap and paid-Gemini gate.
- The **angle** (vector and lane) is shown next to each draft.

### 5.2 Send page, Today tab
- Shows: mailbox, allowance today, sent today, bounce rate over the last 7 days, running or paused, queue counts (scheduled, next send time, deferred outside window, held).
- **Start sending** is the explicit send action required by `CLAUDE.md`. It turns sending on (decision 7 in section 4). When on, the scheduler schedules every approved draft: Touch 2 and 3 first, then new leads, each given a random send time inside its own lead's local window, up to today's allowance; the rest roll to the next weekday. It does not send immediately and it does not blast.
- **Sending state:** a persistent on/off flag (on after Start, off after Pause or an auto-pause, with a reason). The tick works from this flag, so no new Start is needed each day. Approving a draft while sending is on schedules it for the next free slot.
- **Pause** stops the scheduler from sending. Auto-pause at 3% over 20 sends sets the same flag with a reason.

### 5.3 Send page, Follow-ups tab
- Rows are Touch 2 and 3 drafts created by `followups`. Card content as in section 9 of the earlier design (business and owner, which touch, days since Touch 1 and Touch 2, the original email, thread so far, reply and bounce check result with last-checked time, flags, follow-up text, planned slot).
- **Approve**, **Approve all**, **Edit**, **Skip**. A follow-up not approved by its due day stays pending and is marked overdue; it never sends without approval. Leads that replied, bounced or opted out are skipped automatically and listed as skipped with the reason.
- My call: **Skip** cancels only that touch; a later touch still comes due on its own day.

### 5.4 The scheduler
- Runs as a recurring job on the VM worker. Each tick: read replies and bounces first (existing `run_replies`), then send every scheduled draft whose time has come, inside the window, under the allowance, not suppressed, mailbox not paused. The send window (Mon-Fri 9:00-16:00 local, null time zone falls back to America/Chicago) and the allowance logic already exist in `gtm/send.py`.
- Sending creates the Gmail draft from the stored text and sends it (`create_draft` then `send_draft`); Touch 2 and 3 reuse the Touch 1 thread and `In-Reply-To` as today. Idempotent: a touch is claimed (status flips to `sending`) before the Gmail call, so a crash or a second worker cannot send it twice. A claimed touch that never finished is left for the owner to inspect, not retried blindly.
- A tick that finds the Gmail token or API failing pauses sending and shows why on the Today tab.

## 6. Data (my sketch; the builder owns the details)

- `touches` already holds subject, body, objective, status, thread id, `scheduled_for`, `sent_at`, `outcome`. Add: `send_at timestamptz` (the random scheduled instant), `approved_at`, `problems text[]` (failed check codes), and the statuses `held`, `approved`, `scheduled`, `sending`, `cancelled` beside `drafted` and `sent`.
- `batches` gets `draft_instruction text` (the last regenerate instruction).
- Mailbox pause reuses the existing `paused` and `paused_reason`.
- Gmail drafts are no longer created at draft time; the database row is the only draft until send (my call, from section 8 of the earlier design).
- Held drafts are stored as touches with `problems`, so nothing fails silently any more.

## 7. How the UI and worker split the work (my call)

The UI only reads and writes the database and enqueues jobs; it never calls Gemini or Gmail. Jobs for the worker: `redraft` (regenerate a batch with an instruction), `check_drafts` (re-run `check_draft` after edits, so the mechanical rules stay in one place in Python), `schedule` (Start sending) and a recurring `send_tick`. Approve stays disabled until the check job has cleared an edited draft; a short wait after Save is acceptable. If the wait proves annoying, porting the checks to TypeScript is the fallback, accepting the drift risk.

## 8. Acceptance (what "done" means)

1. Unit and database tests for every new rule, run serially under the shared lock (`/tmp/gtm-pytest.lock`); rehearsal rows must use a `REHEARSAL_` prefix, never `TEST_` (the test cleanup deletes `TEST_` rows).
2. Browser check of the Drafts and Send pages (Plan 3b found four bugs that code and database checks missed).
3. A rehearsal to the owner's own Gmail, no real leads: approve in the UI, Start sending, a send inside the window arrives, a reply stops the sequence, a bounce is recorded, Touch 2 and Touch 3 appear in Follow-ups and thread correctly.
4. The same rehearsal on the VM: deploy (queue idle), then run a `send_tick` against a test lead. The Gmail token and a send from the VM are verified; the OS passes on the VM and their memory use on the 1 GB machine are not.
5. The first real send of the 8 Houston leads happens only after the above, with the owner approving each step.

## 9. Left to the builder

Migration details and indexes; how the random send times are chosen within a window while respecting the allowance and spacing; how Start sending and the recurring tick are scheduled on the worker; job progress shown in the UI; the order of migrations and deploy; test structure.

## 10. Risks and unverified items

- The OS `send` and `replies` passes have never run on the VM; memory on the 1 GB machine is unknown.
- Groq's 8K tokens-per-minute wall is untested; a large regenerate that falls back from Vertex could stall.
- The 9:00-16:00 window is the earlier design's guess.
- A reply can take about a minute to become visible to the Gmail API.
- Vertex and `check_drafts` latency after an edit is unmeasured.

## 11. Calls made after the builder review (mine, not agreed by the owner; check these)

1. **Follow-up card data.** The card shows only what the database already holds: the original Touch 1 subject and body, the follow-up text, days since Touch 1, and the touch outcome. "Thread so far" is not stored (no message snapshots). "Reply check, last checked" is the finish time of the last `replies` run, recorded by the scheduler. A full thread view is a later addition.
2. **No migration of old drafts.** The database has zero touches today (checked 2026-11-14); the 8 Houston leads are `selected` and were never drafted. So there is nothing to backfill and no Gmail draft ids to carry over.
3. **One sending path.** The terminal `send --confirm` is kept but becomes a thin caller of the same code the scheduler tick uses (stored text, claim before send, same window and allowance). It is not a second source of truth. It still needs `--confirm`, and `--anytime` still skips the window for rehearsals. The `CLAUDE.md` line "`send` is not job-runnable" is retired when Plan 4 ships: the scheduler tick is the job-driven sender.
4. **Editing an approved or scheduled draft.** An edit clears approval and unschedules the draft: it goes back to `drafted`, `check_drafts` re-runs, and the owner must approve it again. A touch already claimed (`sending`) or `sent` cannot be edited.
5. **Duplicates and blocked leads.** A draft for a lead that is suppressed or already contacted (company or domain duplicate) is shown as held with the reason code (`suppressed`, `already_contacted`) and is excluded from bulk approve. The tick re-checks at send time and cancels a blocked touch rather than sending it.
6. **A `sending` touch left by a crash.** It counts against today's allowance and blocks that lead's later touches until resolved. The Today tab lists it with two actions, **Mark sent** and **Mark failed** (back to approved), so the owner never needs SQL. Recovery is manual by design; there is no blind retry.
7. **Jobs and the tick.** Sending must never wait behind a long `enrich`, `walk` or `redraft`. The tick runs on its own loop (or thread) beside the job queue. Priority when work competes: send tick, then `check_drafts`, then `redraft`. The builder chooses the mechanism; the requirement is that a send is due within a minute of its time regardless of what job is running.
