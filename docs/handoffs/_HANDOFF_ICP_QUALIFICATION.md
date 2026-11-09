# Handoff: ICP qualification before email spend (Phase 9, part 2)

**Written for:** the next Claude Code session on this repo, starting cold.
**Date written:** 29 September 2026.
**Read `CLAUDE.md` first**, then this. Its rules are load-bearing and this task
touches several of them directly.

---

## 1. The ask, in the operator's words

> "I only need med spas in the leads but only leads have map category like dentist
> and more. And also before going for email search I think leads should be filtered
> more so the chance of finding email is a lot more and also more effective leads are
> found. The `MedSpa/` folder contains ICP information — the leads found from Maps and
> the economic buyers found should be based on these files, plus extra checks in order
> to land email more."

Three distinct requests, and they must not be collapsed into one:

1. **Drop businesses that are not the ICP** (a dentist is not a med spa).
2. **Drop "buyers" who are not economic buyers** (a service-of-process agent, a
   staff esthetician and a random employee Hunter happened to list are not buyers).
3. **Qualify before spending email credits**, so the scarce credits land on
   businesses that are worth contacting.

Point 3 is the economic reason the other two matter. See §5 for why it is urgent.

---

## 2. Where the work stands

Phase 9 recon is done and measured. Nothing about §8's engine has been built yet —
`Stage.PERSON_ATTRIBUTION` still raises `StageNotImplementedError("Phase 9")`.
Everything so far lives in one recon script.

| Artifact | What it is |
|---|---|
| `backend/scripts/spike_medspa_ny.py` | The whole recon pipeline. Modes: `--discover --website --npi --dos --linkedin --email --report --csv`. ~2,000 lines, ruff-clean. |
| `backend/data/spike/medspa_ny.json` / `.csv` | Sample 1: 50 businesses (3 tiles × 2 synonyms). |
| `backend/data/spike/medspa_ny2.json` / `.csv` | Sample 2: 150 businesses (12 tiles × 5 synonyms). |
| `ny_medspa_leads_sample.csv`, `ny_medspa_leads_batch2.csv` | Repo-root copies handed to the operator. |
| `implementation.md` §8 | Three dated correction notes holding every measured number. **Read these before changing anything** — several of my early assumptions were measured and found wrong. |
| `README.md` "things worth knowing" | Two traps added: the Maps cache re-run gap and ContactOut's sandbox key. |

Measured outcome of sample 2 (150 businesses): **82 named (55%)**, **37 with an
email (25%)**. Discovery found **1,319 unique NYC med spas**, so the top of the
funnel is not the constraint.

Current state is uncommitted on `main`. Nothing here has been committed yet.

---

## 3. What the ICP files actually say

Source: `MedSpa/`. Authority order is defined inside them; for *qualification*
the operative files are `KodoAI-Med-Spa-ChatGPT-Operating-Guide.md` §5 Stage 2
and `Med-Spa-Touch-1-Research-Master-Prompt.md` §3.

These are written for a human/ChatGPT researcher working **one prospect at a
time**. Your job is not to automate the email writing — it is to automate the
*screening* that happens before it, so a human never spends attention (or a
credit) on a lead the ICP already excludes.

### 3a. Account qualification (§3 of the research prompt)

**Must be** trading in the US or Canada, and one of: med spa, day spa, wellness
spa, cosmetic dermatology, or an aesthetics group **where the relevant service
line is material**.

**Hard stops** (verbatim):
- Closed or rebranded business.
- Aesthetics is a minor add-on.
- Plastic-surgery-only, unrelated salon or unrelated wellness business.
- Franchise-local or location-level contact without authority over the stack.
- No public evidence with which to inspect the relevant journey.
- Do Not Contact, bounce or explicit opt-out.

### 3b. Buyer qualification (§3, same file)

The buyer **must control communications, booking, data or integrations**:
founder, co-founder, owner, CEO, president, COO, executive director, or an
**owner** medical director.

Note the word "owner" qualifying medical director. A salaried medical director is
not automatically a buyer.

### 3c. Priority tiers (§3)

- **A** — founder-controlled, strong current signal, observed handoff, clear relevance.
- **B** — qualified, but objective/authority/handoff has a material ambiguity.
- **C** — larger, investor-backed or MSO account with a surviving group-level angle.

### 3d. The "current signal" gate (§4.1) — the deepest change

Touch 1 requires a **time-bound public event still relevant now**: live hiring, a
dated new location/provider/room/device/service, new advertising or landing page,
new or extended hours, acquisition or platform migration, a new membership or
treatment program.

Explicitly **not sufficient**: a permanent contact form, ordinary published hours,
a general service menu, an undated "coming soon", a website element that may have
existed for years.

**No current signal, no Touch 1** — with one fallback (§4.5 relevance-led) when a
*handoff* is still an observed fact.

This is a real enrichment problem, not a filter. Treat it as its own stage and do
not let it block shipping 3a/3b. See §6 phasing.

---

## 4. What the current data looks like against that ICP

Measured across both CSVs (200 businesses) on 29 Sep 2026. Reproduce with a
`collections.Counter` over the `maps_category` and `buyer_role` columns.

### Category pollution — the operator's complaint, quantified

| Bucket | Count | Categories |
|---|---|---|
| **Core ICP** | 68 | Medical spa |
| **Probable ICP** | ~75 | Skin care clinic (22), Laser hair removal service (21), Facial spa (10), Day spa (5), Dermatologist (3), Esthetics service, Permanent make-up clinic, Health spa, Wellness center |
| **Ambiguous** | ~40 | Spa (16), Massage spa (14), Massage therapist (9) — likely "aesthetics is a minor add-on" hard stops, but needs a service-menu check, not a category guess |
| **Hard stop** | ~17 | Dentist (4), Dermatologist‑adjacent surgical: Plastic surgeon (2), Plastic surgery clinic (2), Cosmetic dentist (2), Chiropractor, Acupuncture clinic, Reflexologist, Lasik surgeon, Nail salon, Hair salon, Beauty salon, Recreation center, Pain control clinic |

So roughly **8–10% are outright hard stops** and another **20% are ambiguous**.

### Buyer-role pollution

Of 82 named people, by the role actually recorded:

| Passes the ICP buyer test | Count |
|---|---|
| founder / founded by / co-founder | 23 |
| CEO (incl. DOS biennial statement) | 18 |
| owner | 2 |
| **Total clearly qualifying** | **~43** |

| Fails or needs a check | Count | Why |
|---|---|---|
| `service-of-process name` (dos_sop) | 14 | A registered-agent/SOP name is frequently a lawyer or filing service, not a buyer |
| `hunter_domain` source | 21 | Hunter's domain search returns *an* employee, not the owner |
| `employee` (JSON-LD) | 3 | schema.org `employee`, explicitly not an owner |
| `medical director` / `clinical director` | 7 | Qualifies **only if owner** — currently unchecked |
| Esthetician, Licensed Acupuncturist, etc. | ~3 | Staff |

**Roughly half the named people in the current CSVs would not pass the ICP buyer
gate.** That is the single biggest quality lever available, and it costs nothing
to apply.

---

## 5. Why this is urgent: the credit position

Free-tier email credits are nearly gone and Hunter — which produced 86% of all
emails found — is empty until **15 October 2026**.

| Vendor | Remaining (29 Sep) | Resets | Measured hit rate |
|---|---|---|---|
| Hunter | **0** of 50 searches | **Oct 15** | ~32% |
| Tomba | 0 today, **5/day** | daily, ~15h | richest payload |
| Snov | 41 credits | Oct 23 | **1 in 44** — near-useless here |
| Prospeo | 96 credits | Oct 24 | ~6%, LinkedIn-URL only |
| RocketReach | 1 | monthly | 3/month total |
| Apollo | **no API on free plan** (403 on every endpoint) | — | — |
| Lusha | blocked: `COMPLIANCE_CONTACT_ERROR` on every contact | — | — |

Check live balances before any run — `implementation.md` §8's vendor note has the
exact account-endpoint calls for each.

**There is a standing backlog of 64 businesses with a name but no email.** At
~5 lookups/day, spending a credit on a dentist or on a service-of-process agent is
a direct loss. Qualification must run *before* `--email`, and `--email` must
process qualified rows in priority order.

---

## 6. What to build

Suggested phasing. Ship 6.1 and 6.2 first — they are cheap, they are the
operator's literal ask, and they immediately protect the credit spend.

### 6.1 `core/icp.py` — a pure qualification module

Follow the `core/` convention: pure functions, no network, no DB, testable from
string literals. Mirror `core/batches.py`, which encodes `_BATCH_SPEC`'s cascade
the same way.

Two independent verdicts, never merged into one score:

```
qualify_account(business) -> AccountVerdict(tier, reasons, evidence)
qualify_buyer(person)     -> BuyerVerdict(tier, reasons, evidence)
```

Model verdicts as an enum, not a boolean: `QUALIFIED` / `AMBIGUOUS` /
`HARD_STOP` / `UNKNOWN`. **`UNKNOWN` must not collapse into `HARD_STOP`** —
CLAUDE.md's "missing data stays missing" rule applies, and the two mean different
things to the operator who reviews the queue.

Every verdict carries the reason as text (`"maps_category=Dentist"`,
`"role=service-of-process name"`), because the operator must be able to audit a
rejection and the ICP explicitly requires evidence classification.

**Encode the category map as data**, next to the §4.1 exclusions in
`taxonomy.EXCLUDED_SOURCES`-style prose so nobody re-adds a dentist without
reading why it was excluded.

Category alone is not enough for the ambiguous bucket — a "Spa" with a Botox and
filler menu is ICP; a "Spa" selling massages is not. Use the already-crawled page
text (it is in the §7 cache; re-parsing costs zero requests) to look for
aesthetics service evidence: botox, filler, dysport, juvederm, laser, microneedling,
coolsculpting, IV therapy, PRP, hydrafacial, morpheus8. Record which terms matched.

### 6.2 Apply it in the spike

- New mode `--qualify` that reads the state file, writes `account` and `buyer`
  verdict blocks per row, and prints the split.
- `--email` skips `HARD_STOP` rows entirely and processes `QUALIFIED` before
  `AMBIGUOUS`. This is the credit-protection change.
- `best_person()` must prefer an ICP-qualifying role. It already has
  `_role_rank`; extend it so a `service_of_process`/`employee`/`hunter_domain`
  person never outranks a founder, and so a non-qualifying person is still
  *recorded* (never discard a contact, per CLAUDE.md §10.1) but not promoted to
  `buyer_name`.
- CSV gains `account_verdict`, `account_reason`, `buyer_verdict`, `buyer_reason`,
  `icp_priority` (A/B/C). Keep every existing column.

### 6.3 `--signal` — the current-signal stage (bigger, do after 6.1/6.2)

This is genuine enrichment and deserves its own recon before it is built. Cheapest
observable signals, in rough order of yield-per-cost:

1. **Job postings** — the ICP's own worked example (22 Spa MD) is a live
   patient-care-coordinator vacancy. Indeed/LinkedIn Jobs via SERP, or the
   careers page already crawled.
2. **News/press via SERP** — `"<business>" (opens OR launches OR expands OR new location)`.
3. **Site freshness** — a dated blog post, a new-provider page, a new service page.
   Crawled bodies are already cached; a re-parse is free.
4. **Instagram recency** — Stage 3 (`sources/social.py`) already renders IG/FB
   logged out. A dated post announcing a new device/provider/hours is a signal.

Record `signal_text`, `signal_source_url`, `signal_date`, and an evidence class of
`observed` / `inferred` / `unknown` — the ICP's §4.5 vocabulary exactly. Then
derive the lane: `observed` → signal-led, weaker-but-handoff-observed →
relevance-led, neither → hold.

**Do not fabricate a signal, and do not let an LLM assert one.** §4.1's "not
sufficient alone" list exists precisely because plausible-sounding non-signals are
the failure mode. If it cannot be dated from a source URL, it is `unknown`.

### 6.4 Extra checks that raise email hit-rate (the operator's "land email more")

These are independent of the ICP and worth doing regardless:

- **Skip domains Hunter has nothing for.** `/v2/email-count` is **free** and
  unmetered. Call it before spending a search; if the domain has 0 emails, the
  finder will miss too.
- **Reject platform hosts as domains.** Already partly done via `_PLATFORM_HOSTS`
  in the spike — extend it. A Hunter search on `vagaro.com` or `x.com` returns the
  vendor's staff.
- **Use the email pattern.** Tomba returns `pattern` (e.g. `{f}{last}`) and Hunter's
  domain search returns one too. With a known pattern plus a name, an address can
  be *constructed* and then verified — and Hunter's verification quota (100/mo) is
  separate from its search quota (50/mo). This is the single largest free-tier win
  available and is currently unused.
- **Prefer businesses with their own domain** — a business on a booking-platform
  subdomain has no findable corporate email.
- **De-duplicate chains before spending.** LaserAway UES and LaserAway Park Slope
  resolved to the same person and the same address; one credit, not two. Note the
  ICP hard-stops "franchise-local contact without authority over the stack" anyway,
  which is the same businesses.

---

## 7. Rules from CLAUDE.md that this task will brush against

- **Missing data stays missing.** An unknown verdict is not a rejection.
- **Never discard a contact (§10.1).** Non-qualifying people stay in the row; they
  are demoted, not deleted.
- **Evidence only ever moves up.** A qualification pass must not lower an existing
  confidence or erase an evidence URL.
- **Provenance survives everything (§1).** Every verdict names the field and value
  that produced it.
- **Never let a source silently return zero.** If `--qualify` rejects everything,
  that is a defect report, not a clean run.
- **Never add a fetch path that bypasses `core/cache.py`.** The service-menu check
  in 6.1 must re-parse cached bodies, not re-fetch.
- **Recon before code.** §5.3 and §6 were both specced from unverified prose and
  both were substantially wrong. Measure the category→ICP mapping against real
  crawled pages on a sample before hard-coding it, and write the numbers into
  `implementation.md` as a dated correction note before building on them.
- **Testing convention.** Each non-obvious assertion gets a docstring naming the
  section it pins. `core/icp.py` should be tested from literals, like
  `core/batches.py`.

---

## 8. Environment notes that will otherwise cost you time

- **`cd backend` before any `uv` command.** A bare `uv run` from the repo root
  picks up system Anaconda and fails confusingly.
- **Docker Desktop stops on its own between sessions.** The §7 cache lives in
  Postgres, so `docker compose up -d postgres redis` and wait for `pg_isready`
  before any spike run. Postgres is on **5433**.
- **`PYTHONIOENCODING=utf-8`** before any script that prints business names, or
  cp1252 raises on names like `CONTŌR`.
- **Never run two scraping scripts concurrently** — duplicate cache-key crash.
- **A cached Maps re-run is thinner than the live one** (269 live vs 102 cached
  for the same 6 queries). `--discover` refuses to overwrite an existing sample
  without `--force` for this reason. Do not re-discover into a state file that
  already has paid enrichment in it.
- **`--exclude <state.json>`** already exists on `--discover` and dedupes new
  samples against old ones on place_id, domain and normalised name. Use it.
- Keys live in `.env`, read only through `config.py`. `HUNTER_API_KEY`,
  `TOMBA_API_KEY`/`TOMBA_API_SECRET`, `SNOV_API_USER_ID`/`SNOV_API_KEY`,
  `PROSPEO_API_KEY`, `ROCKETREACH_API_KEY`, `SERP_API_KEY` are all set and working.
  `APOLLO_API_KEY` and `LUSHA_API_KEY` are set but their accounts do not permit
  API use.

---

## 9. Suggested first session

1. Read `CLAUDE.md`, then `implementation.md` §8's three correction notes, then
   `MedSpa/Med-Spa-Touch-1-Research-Master-Prompt.md` §3 and §4.
2. Bring Postgres up. Confirm the spike still runs: `--report --out ./data/spike/medspa_ny2.json`.
3. **Measure before coding:** for the ~40 ambiguous-category businesses in the two
   samples, re-parse their cached pages and check how many carry aesthetics
   service evidence. That number decides whether category is a usable filter at
   all or whether the service menu has to carry the decision. Write it into
   `implementation.md` as a correction note.
4. Build `core/icp.py` + tests.
5. Add `--qualify`, wire the ordering into `--email`, extend the CSV.
6. Re-run `--qualify` over both existing samples (free — no network) and report
   the split to the operator before spending any credit.
7. Only then consider `--signal`.

**Ask the operator before assuming** on these two open questions:

- Are "Spa" / "Massage spa" / "Massage therapist" in or out when the site shows a
  small injectables menu? The ICP says "aesthetics is a minor add-on" is a hard
  stop, but "material" is a judgment call this data cannot settle alone.
- Should `AMBIGUOUS` rows be queued for a human decision, or auto-skipped when
  credits are scarce? That is an operator preference, not a technical one.
