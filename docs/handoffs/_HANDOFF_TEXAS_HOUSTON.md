# Handoff: Texas med spas, Houston metro first, Hunter key 3

**Written for:** the next Claude Code session on this repo, starting cold.
**Date written:** 7 October 2026.
**Read first, in this order:**
1. `CLAUDE.md` (its rules are load-bearing).
2. `_HANDOFF_ICP_QUALIFICATION.md`, the previous handoff. It gives the background on why ICP screening exists.
3. `implementation.md` §8, the last three notes: "ICP qualification before email spend" and its bullets, including the Utah run.
4. `backend/src/leadscraper/core/icp.py` and `backend/tests/test_icp.py`.

---

## 1. The ask, in the operator's words

> "Now I have pasted Hunter API key 3. Use this to find emails of med spas in
> Texas. This time I also want Texas metropolitan areas distinction, so start
> from Houston. And Hunter credits should only be spent on good leads which are
> top ranked and should not accidentally run Hunter on low level leads like the
> previous run."

Three requirements, each of which needs code before any credit is spent:

1. **Use `HUNTER_API_KEY_3`.** `config.py` currently reads only `HUNTER_API_KEY`.
2. **A metro distinction.** Every row carries its Texas metro. Houston is done first, and the CSV can be split by metro.
3. **A hard eligibility gate on Hunter**, not just a priority order. §3 below explains why ordering alone failed.

---

## 2. Standing operator decisions (do not re-ask)

| Date | Decision | Where it lives |
|---|---|---|
| 30 Sep | A spa or massage business with an **injectables** menu is IN (laser-only is not) | `icp.qualify_account`, `MASSAGE_CATEGORIES` |
| 30 Sep | **No email credit on an ambiguous account.** Only `qualified` accounts are queued | `email_queue` in the spike |
| 7 Oct | **Hunter only on top-ranked good leads.** Never on low-level rows | **not built yet** (your job, §5.3) |

---

## 3. What went wrong in the Utah run: build against this

Utah batch 1 (`backend/data/spike/medspa_ut_b1.json`) was 80 "Medical spa" rows, all with a `qualified` account. Hunter's 21 searches ran out at row 71 and produced 14 emails, of which **only 4 belong to a qualified named buyer**. Measured from the state file on 7 Oct:

| Hunter call | Buyer verdict on that row | Calls | Found |
|---|---|---|---|
| email-finder | qualified | 7 | 1 |
| email-finder | ambiguous | 3 | 2 |
| domain-search | **no buyer at all** | **32** | **1** |
| domain-search | unknown | 3 | 3 |
| domain-search | qualified / ambiguous | 3 | 3 |

(Hunter charged 21 searches for 48 calls. It does not appear to charge an empty domain search, but every call still burned throttle time and verifications.)

The causes:

1. **Ordering is not a gate.** `email_queue` sorts qualified buyers first but then keeps going down the list. Once the named rows were done, the waterfall's last step ran `hunter_domain` (no name, "returns *an* employee") on every row with no buyer. **That is the "low level leads" spend the operator means.**
2. **DNS failed mid-run for the 17 top-ranked rows.** The waterfall recorded them as searched-and-missed and spent the credits further down. This is **fixed**: `--email` now stops on a connection error and leaves the row untried. The 18 affected Utah rows were reset to untried.
3. **Noisy buyer names.** The regex extracted "Nursing Practice", "Frequently Asked Questions" and the business's own name as people. This is **fixed** in `clean_person_name` (`_EDGE_NOISE`, stop words, a business-name-prefix filter). It will not catch everything: **always eyeball the buyer list before a live run** (§6, step 6).
4. Also fixed: a franchise owner is a §3 hard stop, and Prospeo is skipped for a demoted LinkedIn person.

---

## 4. Where the code stands (all uncommitted on `main`)

- `backend/src/leadscraper/core/icp.py` is pure. It holds the account/buyer verdicts (`qualified` / `ambiguous` / `hard_stop` / `unknown`), corroboration across sources, priority B/C (A is unreachable until a signal stage exists), and `queue_key`. There are 55 tests in `tests/test_icp.py`.
- `backend/scripts/spike_medspa_ny.py` despite the name is multi-region:
  - `Region` / `REGIONS` currently hold `ny` and `ut`. `--region` is used at `--discover`, and each row stores `region`.
  - `--dos` (NY Department of State) only runs for regions with `has_registry=True`.
  - Modes: `--discover --website --npi --dos --linkedin --qualify --email --report --csv`.
  - Email flags: `--dry-run`, `--retry-missing`, `--until-hunter-exhausted`.
- The waterfall order is: site email (free) → Tomba (5/day) → Hunter finder → Snov → Prospeo (needs a LinkedIn URL) → RocketReach → **Hunter domain search (only when no buyer is named)**.
- A cached 402/429 from a vendor is refetched, never replayed. Hunter's `cache_key` excludes the API key, so cached answers are shared across keys. That is correct, because a cached "not found" is a fact about the query, not about the key.
- The Utah backlog (27 untried rows in `medspa_ut_b1.json`) is **not** part of this task. Do not spend key 3 on it unless the operator asks.

### Hunter keys, checked live on 7 Oct via the free `/v2/account` endpoint

| `.env` name | Searches | Verifications | Resets |
|---|---|---|---|
| `HUNTER_API_KEY` | 49 / 50 | 98 / 100 | 2 Nov |
| `HUNTER_API_KEY_2` | 0 / 50 | 0 / 100 | 15 Oct |
| **`HUNTER_API_KEY_3`** | **49 / 50** | **98 / 100** | **1 Nov** |
| `HUNTER_API_KEY_4` | 50 / 50 | 100 / 100 | 6 Nov |

Re-check before the live run. **The finder also consumes verifications** (Utah used 42), so budget both. Never print a key. Read keys only through `config.py`.

---

## 5. What to build before any credit is spent

### 5.1 Select the Hunter key

- Add `hunter_api_key_2`, `hunter_api_key_3` and `hunter_api_key_4` to `Settings` in `config.py`, next to `hunter_api_key`. `config.py` is the only reader of `os.environ`. Add the names, with blank values, to `.env.example`.
- Add a `--hunter-key {1,2,3,4}` flag to the spike that picks which one the waterfall and quota use. Default to 1 so nothing changes silently.
- Print which slot is in use and its live balance (from `/v2/account`, free) at the start of `--email`.

### 5.2 Texas, with metros

- Add Texas to `REGIONS` with a **metro** dimension. Suggested shape:
  - A `Region` gains `metros: dict[str, tuple[str, ...]]`: metro slug → fully-qualified Maps query locations.
  - `--metro houston` selects one metro.
  - Each row stores `region="tx"` and `metro="houston"`.
- The CSV gains a `metro` column, **appended** like the ICP columns, so existing column positions don't move.
- **Houston tiles are a hypothesis, like every tile set here.** Starting list: Downtown, Midtown, Montrose, River Oaks, Uptown/Galleria, The Heights, Memorial, Medical Center/Rice Village, Bellaire, plus suburbs The Woodlands, Sugar Land, Katy, Pearland, Cypress, Spring, Kingwood, Clear Lake/League City, Friendswood, Missouri City, Humble, Tomball, Conroe. Write them as `"<area>, Houston, TX"` or `"<suburb>, TX"`.
- ZIP regex for Texas: `\b(7[5-9][0-9]{3}|88[5-9][0-9]{2})(?:-\d{4})?\b`. The second branch is El Paso.
- **Metro is assigned from the query that found the row, then checked.** Maps returns neighbours at the edges, so a Katy query can surface a business in a different metro. Record `metro` from the tile, and record the address city. Report how many rows' address city falls outside the metro's tile list. Do **not** silently drop them.
- When the other metros come later (Dallas–Fort Worth, San Antonio, Austin, …), dedupe them against Houston with the existing `--exclude <state.json>` (place_id, domain, normalised name).
- **No Texas state-registry stage exists.** It might be worth reconning later: the Texas Comptroller's public franchise-tax search may list officers or directors. That is **unverified**. Recon it with a `spike_*.py` through `core/cache.py` before building anything, and do not block this batch on it.

### 5.3 The Hunter eligibility gate: the operator's main requirement

Put the rule in `core/icp.py` as a pure function, with tests, so it is pinned:

```
hunter_eligible(account_verdict, buyer_candidate, own_domain, ...) -> (bool, reason)
```

A Hunter call (finder **or** domain search) is allowed only when **all** of these hold:

1. The account is `qualified`.
2. The chosen buyer is `qualified`: in §3's closed list, directly or by corroboration. `ambiguous` (medical director, SOP name, bare "director") and `unknown` (LinkedIn slug, no role) are **not** eligible by default.
3. The buyer has a usable first and last name, and the business has its **own** domain (`business_domain()` rejects booking platforms by suffix).
4. No earlier free or cheaper step has already produced an address for this row (site email, Tomba).
5. No other row with the **same domain** has already had a Hunter call this run. ClubInject Salt Lake City and ClubInject Bountiful returned the same person at the same address.

**Hunter domain search (no name) is OFF by default.** Gate it behind an explicit `--allow-domain-search` flag; the 32-calls-for-1-email table in §3 is the reason. Record in the row's `email.attempts` why Hunter was skipped (`"skipped": "buyer ambiguous"`), so the CSV can be audited.

**"Top ranked"** means rows that pass the gate, spent in this order:
1. Priority B before C.
2. Buyer evidence strength: site JSON-LD / site text / a corroborated record before a LinkedIn-headline-only buyer. `_EVIDENCE_ORDER` already encodes this.
3. Higher `review_count` (a size proxy; missing ranks last, never as 0).

Also add:
- **`--hunter-budget N`**: a hard cap on live Hunter calls this run, independent of the quota. Default to something conservative, e.g. 25 of the 49.
- **`--dry-run` prints the exact spend plan**: every row that will get a Hunter call, its buyer, its role, its domain and its rank. **Show that list to the operator in the session before the live run.**

Recommendation, not yet an operator decision: apply the same gate to the other metered vendors (Tomba 5/day, Snov, Prospeo, RocketReach). They are just as scarce. Ask if unsure.

Tests to write (`tests/test_icp.py`, literals only):
- Each gate condition rejects on its own.
- An ambiguous buyer is ineligible.
- No buyer means no domain search unless explicitly allowed.
- The second location on the same domain is skipped.
- Priority order is B before C, then evidence strength, then review count, with missing last.

Each test gets a docstring naming the Utah measurement that forced it.

---

## 6. Run order for Houston

From `backend/`, with `PYTHONIOENCODING=utf-8`. Never run two scraping commands at once.

1. `docker compose up -d postgres redis` from the repo root (Docker Desktop stops on its own between sessions; start it first). Wait for `pg_isready`. Postgres is on **5433**.
2. **Discover:**
   ```
   PROXY_REQUIRED_SOURCES="" uv run python scripts/spike_medspa_ny.py --discover --region tx --metro houston --synonyms 3 --limit 2000 --out ./data/spike/medspa_tx_houston.json
   ```
   Utah's 48 queries found 1,727 unique businesses with 0 blocks, so expect a similar pool. Keep the full pool in this file and never re-discover into it: a cached Maps re-run is thinner than the live one (README trap).
3. **Slice batch 1:** "Medical spa" category, a Texas ZIP and its own domain, 80 rows, in the file's already-shuffled order → `medspa_tx_houston_b1.json`. Utah did this with a few lines of Python; consider adding a `--slice` mode so it is reproducible.
4. `--website` on the batch. Utah: 80 sites, 28 with a named person on the site.
5. `--linkedin` on the batch (Serper; had 2,139 credits on 30 Sep). **Skip `--npi`**: it named nobody in 200 NY businesses.
6. `--qualify`, then **eyeball every chosen buyer**: name, source, role, page snippet. Utah's helper script was ad hoc; add a `--buyers` mode that prints exactly that. Fix new noise patterns in `clean_person_name` and re-run `--website --force`. That re-parses from the §7 cache and costs no requests.
7. `--email --dry-run --hunter-key 3` → **show the spend plan to the operator.**
8. The live run: `--email --hunter-key 3 --hunter-budget N`. Watch the log for `!! … ConnectError`; the run now stops itself on a network error.
9. `--csv`, then copy the result to the repo root as `texas_houston_medspa_leads.csv`.
10. If the budget remains and the operator wants more, slice batch 2 with `--exclude`, and repeat steps 4–9.

---

## 7. Reporting back and docs

Report these to the operator:
- The discovery count.
- The account and buyer split.
- How many rows the gate admitted.
- Hunter calls made against budget, and emails found.
- **How many emails belong to a qualified named buyer**, which is the number that matters.
- Any rows where `email_person` ≠ `buyer_name`.

Update in the same change as the code (CLAUDE.md requires it):
- `implementation.md` §8: a dated note with the Houston numbers and the gate's effect against Utah's 32-domain-searches-for-1-email.
- `README.md` "things worth knowing": `--hunter-key`, the gate, `--metro`.

The green bar is `uv run pytest` passing and `uv run ruff check .` clean. A repo-wide `ruff format --check` flags a few pre-existing files you did not touch; leave them alone.

Nothing has been committed since `4313d58`. Ask the operator before committing.
