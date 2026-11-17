# Plan 5 outline: sheet import and the manual queue

Date: 2026-11-17. Status: **outline only, nothing built, nothing approved.** It is the starting point for the Plan 5 brainstorm (`superpowers:brainstorming`), then a written design in `docs/superpowers/specs/`, then `superpowers:writing-plans`, then the build. Sources: roadmap row 5 (`2026-11-12-gtm-os-roadmap.md`), design section 7 and calls 15.3, 15.4, 15.10, 15.11 (`docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md`), the owner's description of their manual flow (2026-11-14), and CLAUDE.md. Facts are marked **Owner** (said by the owner), **Design** (written in the approved design, not re-checked), or **My guess** (unconfirmed).

## 1. The goal in one paragraph

Before the OS, the owner worked from a Google Sheet "MedSpa": scrape Maps with an extension, have ChatGPT verify and enrich each lead one by one, find emails with Hunter and ContactOut, send, then colour the row (**green = email sent, red = dropped for any reason**, no colour = unknown). Plan 5 brings that sheet into the OS so none of that work is lost or repeated, and keeps the one step the OS cannot do by itself, the ContactOut email lookup, as a small daily round trip through a sheet tab. It does not change the send flow built in Plan 4.

## 2. What is already decided (do not re-open without the owner)

- **Colour rule** (Owner, confirmed 2026-11-12): any green cell in a row = sent; any red cell = dropped; no colour = unknown but still a potential lead. Colouring is per row, some cells uncoloured, so the mark can sit on any cell. (Design)
- **Green rows** become "already contacted" suppression entries (most already are, from the Notion import). **Red rows** become "never use". **Uncoloured rows with an email** become candidate leads. (Design)
- **Candidates pass the same gates as scraped leads:** suppression and already-contacted, domain dedupe, no day spas or other excluded categories, no registered-agent "owners" (the New York tab has 14 rows labelled "service-of-process name"), email verification, decision-maker title. Multi-email cells are split. (Design)
- **Identity:** a Google place id when the row has one (Texas and New York carry a Maps URL; Utah's second block has none), else a synthetic key `domain:<domain>` in the existing unique `place_id` column; a real id replaces it later. (Design 15.4)
- **Verification rule:** the same as for any lead: Hunter `valid` and score at least 80; `accept_all` fails; a `webmail` status does not pass until measured; each verification costs 0.5 Hunter credit; free-mail addresses are verified the same way. (Design 15.10; owner 2026-11-14: no `accept_all` lowering, no bounce-rate increase, buy Hunter credits only once the OS can run a campaign)
- **Manual queue:** each morning the OS writes the best named-but-no-email leads (owner name, domain, LinkedIn search link) to a tab of the same sheet; the owner pastes emails from ContactOut (about 5 a day); the OS reads them back, verifies each, and enriches the lead if it passes. A pasted email that fails verification leaves the lead `no_buyer` and it is **not re-queued**. Queue order: named owner, LinkedIn URL present, then review count and rating descending. (Design 15.11)
- **Sheet access:** a service account shared on the sheet as Editor; colours read through the Sheets API formatting fields, not values. (Design 15.3, but see open question 1: the account setup changed.)
- **The import is a one-time job plus re-runnable;** each tab needs its own column mapping (Utah even has two stacked blocks). (Design)
- Known sizes (analysis 2026-11-12): 341 rows, 164 with an email; 84 uncoloured with an email, about 53 not already suppressed or ours; 38 Texas and 134 New York uncoloured rows with no email, plus Houston leads saved as named-but-no-email, form the initial manual-queue pool.

## 3. Open questions to settle in the brainstorm (most important first)

1. **Which Google account owns the sheet, and how does the OS read and write it?** The design assumed a service account "in the same Google Cloud project". The accounts have since been clarified: `soban@kodoai.xyz` owns GCP project `kodoai-gtm-os` (Gmail API only), `sobanahmad2003@gmail.com` owns `gen-lang-client-0603350481` (Gemini, the VM), and the Workspace admin is `soban@sobanahmad.dev` (see HANDOFF section 0(c)). Options to choose between: a service account in either project shared on the sheet; OAuth as `soban@kodoai.xyz` (the Gmail OAuth client could add the Sheets scope); or the Google Sheets connector available in Claude sessions (recon only, not for the OS itself). It decides the secrets, the VM access and who must share the sheet.
2. **Can colours be read reliably?** The Sheets API returns formatting only when grid data is requested; the connector tools in a Claude session may not expose it. My guess: needs a direct API call. Verify on the real sheet before designing around it.
3. **What exactly do the three tabs look like?** Column names, header rows, the second Utah block, how emails and owner names appear, Maps URLs. Needs a read-only recon of the real sheet (the sheet link is supplied by the owner and stored in Settings, never in the repo).
4. **Where do imported candidates enter the pipeline?** They carry an email already. Do they skip scraping and cleaning and go straight to verification, then `signalled`, `select`, `draft` like any lead? Which statuses do green/red rows get, and are red rows stored as leads at all or only as suppression entries? My guess: green and red become suppression rows only, candidates become `cleaned` leads with a `domain:` key.
5. **How are rows re-imported without duplicates?** Re-runnable import means stable row keys; what happens when the owner edits a row after import.
6. **Manual queue mechanics:** write once a day (a scheduled job on the VM?) or on demand; how many rows per day (about 5 by the owner's ContactOut limit); does the OS clear or archive finished rows; what the owner sees in the tab; how a failed verification is shown back.
7. **Hunter credits:** verification costs 0.5 credit each. The free keys are limited; the owner buys a plan only once the OS can run a campaign. How many credits may the import spend on the 53 candidates, and is that confirmed before any run?
8. **A Manual queue page in the UI?** The design's page table lists one ("Manual queue: best named-but-no-email leads for ContactOut lookup"). Decide whether it is needed beyond the sheet tab.

## 4. Proposed scope (my guess, for the owner to confirm or cut)

**In:** read-only sheet reader with colour parsing; per-tab column mapping stored as data; the import job (green and red to suppression, candidates to leads, gates, `domain:` keys, dry run first with a report); candidate verification with a Hunter budget gate; the manual queue writer and read-back job; Settings for the sheet id and the daily queue size; tests and a dry-run report the owner reads before anything is written.

**Out:** any change to scraping, enrichment finders, drafting or sending (Plans 3 and 4); the Gemini assistant window; Plan 6 metrics; a second mailbox.

**Hard rules for this plan (from CLAUDE.md and the owner):** nothing writes to the real sheet and no paid verification runs without the owner's yes; the import starts as a dry run that prints what it would do; suppression is checked before every draft and send; `place_id` stays globally unique; never invent an email or a signal.

## 5. Proposed shape of the build (my guess; the brainstorm may change it)

New modules under `gtm/` (names are placeholders): `sheet.py` (Sheets API client, colour parsing), `sheet_import.py` (mapping, gates, dry run), `manual_queue.py` (select, write, read back), plus settings keys and, if needed, one additive migration. A UI page only if question 8 says yes. Jobs run on the existing worker through the CLI route (`gtm.cli <kind>`), like `walk` and `check-drafts`.

## 6. How the work should be executed (sub-agent driven, parallel, three levels)

Method: `superpowers:subagent-driven-development`, same as Plan 4. The main session is the **orchestrator**: it dispatches agents, owns merges, migrations, the full test suite and the PR, and does not edit product code itself.

**Order of work**
1. **Brainstorm with the owner** (`superpowers:brainstorming`): settle section 3, in particular questions 1 to 4. A read-only **recon agent** may read the real sheet first (owner supplies access), reporting tab shapes and whether colours are readable. Output: a written design in `docs/superpowers/specs/`, then the owner's approval, then `superpowers:writing-plans`.
2. **Wave 1, parallel groups** (each in its own git worktree and branch, one agent per group, dispatched in one message): **A** sheet reader and colour parser (the access decision from question 1); **B** import pipeline (mapping, gates, dry run, `domain:` keys); **C** manual queue (selection, writer, read-back, verification); **D** settings and, if wanted, the UI page.
3. **Sub-agents, one level inside a group:** B spawns one sub-agent per tab mapping (Utah, New York, Texas) once the shared mapping schema exists; C spawns one for the queue selection query and one for the writer and read-back; D spawns one per page or setting.
4. **Sub-sub-agents, two levels deep, only where work is independent:** a tab sub-agent may spawn one for fixtures and tests of that tab's edge cases (the two stacked Utah blocks, the 14 registered-agent rows, multi-email cells). Nothing deeper.
5. **Per task:** a fresh reviewer agent reads the task text and diff, then a ponytail review pass. **After the merge:** one whole-branch reviewer over the combined branch, then the full suite, then the PR. Wave 1.5 (merge, suite) and the final acceptance (a dry-run report the owner reads; any real write or paid verification only on the owner's yes) mirror Plan 4.

**Every agent, at every level, starts with this preamble**
1. Invoke `ponytail:ponytail` (shortest working diff, no speculative abstractions, one runnable check per non-trivial rule) and `superpowers:test-driven-development`; use `superpowers:verification-before-completion` before any claim of done. The orchestrator uses `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development` and `superpowers:dispatching-parallel-agents`.
2. Use `graphify` (`graphify-out/` exists): read `graphify-out/GRAPH_REPORT.md` and query the graph before grepping for callers or signatures; refresh the graph after structural changes.
3. Read the Plan 5 design and plan, CLAUDE.md (especially Rules and Sending) and only your own tasks; edit only your tasks' files; stop and report if something outside is needed.
4. Shared-resource rules that broke earlier parallel runs: one pytest process at a time (`until mkdir /tmp/gtm-pytest.lock 2>/dev/null; do sleep 10; done`, `rmdir` right after); hand-made rows use a per-group prefix `REHEARSAL_` and never `TEST_`; tests must never touch the real mailbox row (a conftest guard fails the run if they do); run only your own test files until the merge.
5. Hard gates, stop and ask the owner: applying a migration; any write to the real sheet; any paid call (Hunter verification, Gemini beyond tests); deploying to the VM (queue idle first); merging to `main`. Agents open no PRs, never commit to `main`, never print keys.

## 7. Dependencies and facts a builder needs

- **Depends on** Plan 1 only (settings, budget caps, jobs, worker). Nothing in Plans 3 and 4 blocks it; imported candidates should flow into the existing clean, enrich, signals, select, draft pipeline.
- **Existing pieces to reuse:** suppression and `blocked_reason` (`gtm/select.py`), the Hunter verifier path in the enrichment finders (`gtm/enrich*`, see `docs/spikes/hunter.md`), `chains.txt` for multi-location groups, the budget gate (`gtm/budget.py`, `require` then `log_cost`), `settings_store` plus the mirrored `web/lib/settings.ts`, the worker's CLI-pass route.
- **Unverified:** the sheet's current content (last analysed 2026-11-12), whether colours are readable through the tools the OS will use, Hunter's behaviour on every address type in the sheet, and how many of the 53 candidates survive the gates.

## 8. First actions when the brainstorm starts

1. Ask the owner for the sheet link and who owns it (open question 1).
2. Run the read-only recon (open questions 2 and 3) and bring back the tab shapes and the colour finding.
3. Decide open questions 4 to 8, then write the design and the plan.
