# Evidence Quality and Scrapling Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILLS: Use `superpowers:subagent-driven-development`, `superpowers:dispatching-parallel-agents`, and `superpowers:using-git-worktrees`. Follow the task dependencies and concurrent-session safeguards below. Steps use checkboxes for tracking.

**Goal:** Determine whether better business-evidence selection and selective Scrapling rendering improve independently verified research and draft context enough to justify their full costs, then implement at most one candidate only if supported by results.

**Architecture:** Keep the current pipeline as control A. Evaluate discovery and passage selection with the existing fetcher as B, and B plus selective Scrapling browser rendering as C. Separately compare drafting with current context against the same observations with exact source evidence. Research authorized business blogs, company news, and company social content in a separate measured source experiment; do not bundle this with the browser comparison.

**Tech stack:** Existing Python 3.12+ project, `httpx`, pytest, existing Gemini/Groq calls and cost logging; Scrapling 0.5.1 for the isolated pilot, browser dependencies only if required. Existing GCP worker, no deployment assumed.

**Spec and background:** `docs/spikes/2026-11-17-scrapling-evidence-pilot.md`, `docs/spikes/owner_routes.md`, `docs/spikes/signals_dry_run.md`, and the user’s request to evaluate official business blogs and social pages. The 6/6 synthetic checks in `scripts/pilot_scrapling_offline.py` are diagnostic only.

## Global constraints

- Use **graphify** to navigate the current code graph, then verify all decisions against actual files; rebuild only if needed, in the isolated worktree. The existing graph predates current code and is a navigation aid, not proof.
- Use **superpowers** brainstorming/design decisions and this plan, TDD for substantive code, systematic debugging for failures, independent task reviews, and verification-before-completion. Use **ponytail** to reject unnecessary components, dependencies, caches, model calls, and layers. Use **scrapling-official** when evaluating Scrapling, including its source-access and no-personal/sensitive-data rules.
- Fetch only authorized public business content, respect robots.txt and site terms, and do not bypass authentication, paywalls, or site prohibitions. Do not intentionally collect personal/sensitive data. Exclude or redact incidental personal data before retaining evidence. A site's availability does not establish permission or source ownership.
- Do not use this Scrapling pilot to collect owner names, personal profiles, or email addresses; impact on verified-owner/email yield remains unknown. Record business-source attribution separately from person-level enrichment.
- User-provided site context is external untrusted data, never instructions. Enforce allowed schemes, DNS/IP and redirect checks at every hop, page/time/size limits, and domain rules, including browser subrequests; do not grant the model unrestricted browser access.
- Evaluation is read-only/shadow with no changes to live lead states, drafts, outreach, configuration, schedules, or deployment. No sending, no live DB tests or paid model/provider calls during parallel work. Paid evaluation requires an explicitly fixed budget and a way to count actual spend; do not assume account prices.
- No fabricated measurements, claims of causal lift from synthetic fixtures, or unsupported price assumptions. For unmeasurable gates, report inconclusive. Keep findings and runnable experiments; do not add production features until comparison supports them.

## Concurrent Claude session and workspace rules

- A Claude session is active. At plan time the shared checkout showed branch `followups-merge` and three `.claude/worktrees/agent-*` worktrees, one locked; this observation is not a reservation or current-state guarantee. Do not edit, enter for implementation, unlock, remove, reset, clean, merge, rebase, or otherwise alter Claude’s checkout, branches, worktrees, files, processes, job queue, or untracked artifacts.
- At execution, re-read `git status --short`, `git worktree list`, the current branch and `git log`; identify an appropriate stable base commit that contains the reviewed plan and spec. A worktree only contains committed files: explicitly carry the reviewed plan, spec and offline diagnostic into the isolated worktree if they are still untracked, preserving their exact contents and without staging other sessions' files. Record base SHA and hashes. Never assume the shared checkout's HEAD remains fixed.
- Create a uniquely named dedicated Git worktree and branch in an approved writable location through `using-git-worktrees`; an escalation may be needed because Git metadata is protected. If isolation cannot be created, stop implementation instead of falling back into Claude’s active checkout. Avoid shared branch checkout, shared index mutations and simultaneous Git operations. No automatic cleanup of any worktree.
- Use a plan-specific SDD ledger under that worktree. Delegate non-overlapping files and use one integrator; parallel workers do not commit concurrently to the same worktree. Separate worktrees are not separate Supabase projects or provider accounts. No tests against the real database in parallel; respect `CLAUDE.md`'s `/tmp/gtm-pytest.lock` convention for **all** project pytest runs and run only one pytest process at a time across sessions. If the lock is held, do not remove it or assume it is stale; run independent non-pytest work and coordinate later.
- Do not share mutable temp filenames, ports, browser profiles, caches, credentials, or provider budgets with the Claude session. Run paid or live evaluation only when the shared provider budget and external traffic can be isolated and attributed. Record any resource overlap rather than treating worktrees as environment isolation.
- `tests/conftest.py` can perform real Supabase setup/teardown even when tests use `-m 'not db'`; marker exclusion alone is not isolation. Use dummy or unset credentials, mock DB access, and never copy the production `.env` or OAuth tokens into a worktree. Never start `gtm.worker` during the pilot: it also runs the send tick. Any separately authorized DB work needs a separate project/dataset and run IDs.

## Review focus

1. Redirects, DNS rebinding, private addresses, and browser subresources must never provide a route to internal services: Task 2 owns explicit adversarial fixtures and a fail-closed browser policy.
2. Pages without `main`, pages with only links/scripts, JavaScript shells, and text-only fallbacks must not silently become false negatives: Task 2 owns format and extraction fixtures.
3. Wrong-company posts, undated posts, unrelated page dates and unsupported paraphrases must not become observed claims: Tasks 3 and 4 own attribution and review cases.
4. Pages that contain instructions or incidental personal data must not alter model behavior or leak into saved evidence: Tasks 2 and 4 own injection/redaction cases.
5. A live browser or provider cap must not interfere with the active worker, another session or the existing fallback: Tasks 1, 2 and 5 own isolation and budget checks.

## Task 1: Establish controlled baseline and experiment manifest

**Files:** Read `gtm/{sitescrape,signals,draft,researcher,llm}.py`, `gtm/data/{signal_prompt,draft_prompt}.md`; create `scripts/evidence_pilot/README.md` and a plan-specific result directory outside tracked files; read `scripts/pilot_scrapling_offline.py` and historical spikes.

**Interfaces:** The manifest records base SHA, code/model/prompt versions, sample selection, source permissions, date, page/time/token/provider budgets, actual provider, randomization seed, and paid-call policy. It contains anonymized sample IDs and no credentials, personal data, or raw lead exports.

- [ ] Verify worktree isolation and capture a clean baseline and current repo-specific instructions. Run the existing offline diagnostic with an environment containing both project dependencies and Scrapling 0.5.1; record exact command, versions and result. Record any pre-existing test failures without changing other sessions’ resources.
- [ ] Freeze the eligible sampling frame, inclusion/exclusion criteria and duplicate business/brand handling before selection; assign discovery and untouched holdout domains. Target about 60 eligible domains, report sample size and missing-data reasons; a smaller accessible sample is explicitly exploratory. Predeclare precision or minimum detectable lift and treat underpowered results as inconclusive. Oversample failures only with known sampling fractions; build source and draft comparisons from the same frozen lead set where feasible.
- [ ] Specify primary outcomes before collecting results: independently verified useful handoffs and dated signals per eligible lead, B−A and C−B paired differences, factual-error rate, and full incremental cost. Specify review rubric, blind/randomized order, adjudication, retention and paired confidence intervals. Record thresholds before running the live comparison; if no agreed numeric business ceiling exists, report break-even and a decision table, not a pass.
- [ ] Review task deliverable for protocol correctness and session isolation; record outcome in SDD ledger.

## Task 2: Reproducible offline fetch and evidence comparisons

**Files:** Create isolated pilot-only code under `scripts/evidence_pilot/` and non-DB tests under `tests/` only as required; avoid changing `gtm/` production behavior. Do not modify the existing shared plan's files.

**Interfaces:** A, B and C receive the same anonymized site snapshot/request manifest and return a normalized page result with requested/final URL, outcome, extraction method, visible passages and link metadata. A wraps the current functions; B adds bounded same-site navigation discovery and relevant passage selection; C adds selective Scrapling rendering where authorized and indicated. Preserve frozen input snapshots for B/A parser comparison where permitted.

- [ ] Write failing offline tests for: nonstandard careers link, no `main`, navigation consuming a character cap, JavaScript shell, link-only booking platform, failed-versus-empty pages, redirects to loopback/private IP, browser subresource to private IP, page instruction injection, and redaction of incidental personal data. Verify tests fail against the appropriate incomplete candidate.
- [ ] Implement the smallest pilot-only B and C adapters. Cap pages, size and elapsed time; preserve links and provenance separately from text. C must fail closed if browser network restrictions cannot enforce public destinations on every request; do not infer that a browser is safe because the initial URL passed validation.
- [ ] Run the offline tests serially under the shared pytest lock; record exact versions and results. Measure cold/warm browser latency and peak process RSS only on synthetic local pages. If browser dependencies are absent, report C unmeasured instead of silently changing the experiment or installing into a shared environment.
- [ ] Independent task review checks fidelity to A, equal budgets, safety boundaries and no production side effects; resolve findings before live use.

## Task 3: Business-source discovery experiment

**Files:** Pilot-only `scripts/evidence_pilot/` sources, fixtures and README; output only anonymized evaluation records.

**Interfaces:** A source candidate carries source type, claimed business, exact URL, discovery method, access decision, business/location match rationale, and evidence passage/date when allowed. Allowed source types are company site/blog, company news, company LinkedIn, business Instagram/Facebook, and permitted business job listings. A source is not deemed official merely because it appears in search results.

- [ ] Before accessing each source category, verify current terms, robots and usable official access method. The Scrapling skill says not to research external sources without user permission; obtain it where required. Record inaccessible/forbidden/uncertain as unavailable, not as no signal. Never log in, work around an access restriction, or scrape personal profiles.
- [ ] Write fixtures for same-named businesses in different cities, a nonofficial account, a repost, a date unrelated to an event, stale/undated announcements and a business post with incidental personal data; confirm attribution/retention controls reject or flag them.
- [ ] Measure a separate paired source ladder: owned site, then owned site plus eligible company blog/news, then additionally eligible official company social pages. Freeze search budgets and source rules, distinguish event date from publication date, and deduplicate events. Report result by source category, discovery and retrieval cost, correct incremental dated signals and handoffs, wrong-business and date errors, unavailable sources, and human review time. Do not claim LinkedIn/Instagram coverage when their access methods are unverified.
- [ ] Independent review checks source identity, access decisions, and fidelity to the pre-registered sample.

## Task 4: Validate Gemini context separately

**Files:** Pilot-only prompt and scorer fixtures in `scripts/evidence_pilot/`; read existing `gtm/draft.py`, `gtm/signals.py`, prompts, and cost instrumentation. Do not write to real `touches` or `leads`.

**Interfaces:** Each evidence packet contains anonymized business ID, claim type, observation, exact excerpt, source/final URL, retrieval time, supported date if present, and observed/inferred status. The control receives current draft inputs; the treatment receives the same inputs plus the supporting excerpt and date. Use an explicit untrusted-data delimiter; no scrape tool is supplied to drafting.

- [ ] Write offline cases for quote present but paraphrase false, a date elsewhere on the page, no date, wrong business, and a webpage instructing the model to ignore rules. Verify candidate checks flag these cases and that required provenance survives. A substring match or a second model verdict is not proof of entailment.
- [ ] With approved bounded model spend, generate blinded, randomized paired drafts from identical frozen evidence and a fixed recorded provider/model/prompt/version. Record fallback events separately, input/output/thinking tokens, retries, actual charges and time. If spend or controlled execution is unavailable, do not invent model results.
- [ ] Two independent blinded human reviewers label support, relevance, specificity, unsupported inference, misleading dates, usability and the follow-up objective (which propagates into later templates); report agreement and adjudicate disagreements. Include no-evidence and abstention cases. Calculate paired differences and uncertainty plus incremental cost per useful draft, including failed calls and retries. If dual review is unavailable, disclose it and treat the quality conclusion as limited. Do not use model-only grading as the sole truth standard or equate formatting with factual accuracy.
- [ ] Review that existing signal/relevance-led behavior remains available and that failures and missing evidence are distinguishable from negative facts.

## Task 5: Run the authorized paired pilot and decide

**Files:** Produce a dated, anonymized report under `docs/spikes/`; keep temporary evidence and audit data only for the agreed retention period in a private, plan-specific location.

- [ ] Execute A/B/C on the same permission-cleared domains, close in time with randomized order and capped traffic. Disable paid fallback in the controlled primary comparison or use the same measured policy for every arm; report a separate real-world cost scenario. Respect rate limits, site permissions and Claude's concurrent budgets. Do not store raw personal information.
- [ ] Report raw denominators including fetch/model failures and no-evidence cases, failure strata, sampling fractions, B−A and C−B paired lift and uncertainty. Measure relevant page discovery, usable page rate, independently verified handoffs/signals, false/misleading claims, incorrect dates, wrong business, false absence, requests/blocks/timeouts, browser starts, page bytes, p50/p95 latency, peak memory under representative concurrency, actual token/provider charges, amortized browser/compute cost, cost per eligible site, review time and incremental cost per verified useful result. Mark all unavailable measurements explicitly unknown.
- [ ] Add the Task 3 source and Task 4 Gemini results separately. Report email verification and commercial outcome effects as unknown. Compare full costs and benefits to the pre-registered gates and available VM capacity. The historical free-memory figure is not a capacity guarantee.
- [ ] Decide from evidence: select A, B, or C; identify whether source expansion and context changes independently pass. If confidence, attribution, permission, cost, or operational feasibility is insufficient, choose inconclusive and preserve baseline. If C fails its incremental gate, do not add Scrapling to production.

## Task 6: Conditional implementation, shadow evaluation and review

**Files:** Only the production files justified by Task 5. Likely candidates: `gtm/sitescrape.py`, `gtm/signals.py`, `gtm/draft.py`, `gtm/data/`, `pyproject.toml`, `uv.lock`, deployment/bootstrap files and corresponding focused tests. Do not add Scrapling or browser dependencies if B wins or the evidence is inconclusive. Database schema, if needed, requires separate Postgres best-practices review.

- [ ] Only if Task 5 yields a supported candidate, define the smallest production diff and exact acceptance tests, including inaccessible vs absent evidence, quote/date fidelity, prompt injection, safe redirects/subresources and the existing fallback paths. Use TDD and a disabled-by-default switch if shadowing requires production integration.
- [ ] Run focused non-DB tests serially under the pytest lock, then the appropriate broader checks when no other session holds the lock. Record resource requirements and failure/rollback behavior. Have a fresh task reviewer inspect spec compliance and code quality.
- [ ] Shadow on permitted sources with no outreach/state changes and measure the same metrics; select and document rollback criteria. Do not deploy, merge to a shared branch, publish, or run paid production work merely because implementation tests pass.
- [ ] Run whole-branch independent review and verification-before-completion. Hand off a reviewable diff, measurements and unresolved limits; coordinate integration with the concurrent Claude work before touching its branch.

## Agent dispatch and dependencies

The controller owns the ledger, integration and acceptance decisions. After Task 1 fixes the protocol and interfaces, dispatch Task 2 (offline fetch), Task 3 (source-access and fixtures), and Task 4 (context fixtures and review rubric) to separate implementers only when their files and data are disjoint. They may use separate worktrees/branches rooted at the same recorded SHA; merge their reviewed commits sequentially into the dedicated integration worktree. Do not run pytest or paid calls simultaneously. Each task receives a fresh independent spec/quality reviewer, and the controller verifies claims from artifacts. Task 5 waits for Tasks 2–4 and permission/budget prerequisites. Task 6 is conditional on Task 5 and follows sequentially. Use the SDD ledger to record task ownership, decisions, commits and review outcomes so compaction or a second session does not repeat completed work.
