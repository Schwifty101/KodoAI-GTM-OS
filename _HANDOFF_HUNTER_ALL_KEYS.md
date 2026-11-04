# Handoff: all four Hunter keys, no accept-all emails, appended to the Texas master list

**Date written:** 29 October 2026.
**Read first, in this order:**
1. `CLAUDE.md`. Its rules are load-bearing.
2. This file, all of it, before running anything.
3. `_HANDOFF_TEXAS_HOUSTON.md`. That handoff is done, and this one builds on it.
4. `implementation.md` §8, the last two bullets: "Texas, Houston metro, batch 1" and "Spending key 3 down, batches 2–3".

---

## 1. The ask, in the operator's words

> "A new session will use all three four api keys at once and those emails will be
> stored whose email score is above 80 and also high scoring linkdin (if email not
> found just like the current leads in texas csv). The new session will append to
> this list hopefully scoring 170-180 above 80 leads along with extra linkdin links
> (no emails)."

The operator then clarified (29 Oct): **"what I meant by above 80 was basically don't
include accept all emails … whether these are below 80 or other reason."** The rule is
the verification status, not the score.

That breaks down into five requirements:

1. **Spend Hunter keys 1–4 in one run**, rotating to the next key when one is exhausted. This is **not built**. Today's code takes one `--hunter-key` per run (§4.1).
2. **Never store an `accept_all` email.** `email_verification == "accept_all"` means the domain's mail server accepts any address, so this particular address is unconfirmed. Every other found email is stored, whatever its `email_score`: Hunter or Tomba `valid`, Prospeo `VERIFIED`, and the business's own published address (`site_personal`, which has no verification). This is an *export* filter, not a spend filter: Hunter charges the search before anyone knows the result is accept-all.
3. **Also store LinkedIn rows**: a qualified buyer (§3 below) with a LinkedIn URL, where no storable email was found.
4. **Append to `texas_medspa_leads_master.csv`** at the repo root. Never rewrite it from scratch.
5. **Target: about 170–180 `email` rows in total.** The master holds 44 today. §5 shows the arithmetic. The target is reachable only by spending the keys *both before and after* their resets, and only with more pool than one metro provides.

## 2. Standing operator decisions (do not re-ask)

| Date | Decision |
|---|---|
| 30 Sep | A spa or massage business with an **injectables** menu is IN; laser-only is not. |
| 30 Sep | **No email credit on an ambiguous account.** Only `qualified` accounts are queued. |
| 7 Oct | **Hunter only on top-ranked good leads.** The gate in `icp.hunter_eligible` enforces this; see §3. |
| 7 Oct | **Use a key's allowance fully.** Widen the *volume* (more rows, more metros), not the gate. Batch 1's 12 calls drew the comment "you are using hunter too cautiously". |
| 7 Oct | Do **not** gate Tomba, Snov, Prospeo or RocketReach (`--gate-all-metered` stays off). All four ran dry anyway; see §6. |
| 8 Oct | Asked whether to spend key 3's last 4 searches on medical directors (ambiguous buyers), the operator said **"keep them"**. So do not loosen the buyer gate without asking. |
| 29 Oct | **Master-list rule:** store every found email **except `accept_all`**, whatever its score. Otherwise store a qualified buyer's LinkedIn. An earlier reading ("score ≥80") was wrong; do not reintroduce a score threshold. |

## 3. What was built, and why the leads are good

All of this is in `backend/scripts/spike_medspa_ny.py` and `backend/src/leadscraper/core/icp.py`. It is uncommitted on `main`; ask the operator before committing.

### 3.1 The pipeline, per batch

| Mode | What it does | Costs |
|---|---|---|
| `--discover --region tx --metro <m> --tiles 0 --synonyms 3` | Maps queries, one metro at a time; each row stores `metro` and `address_city` | free (no proxy needed, 0 blocks measured) |
| `--slice --into <file> --size N --category "A,B" --exclude <files>` | Cuts a batch: listed categories, in-state ZIP, own domain | free |
| `--website` | Crawls each site and extracts named people, emails and LinkedIn links | free, slow |
| `--qualify` | ICP account and buyer verdicts, read from cached pages | free |
| `--linkedin` | Serper `site:linkedin.com/in` lookup | **Serper credits** |
| `--buyers` | Prints every chosen buyer with a snippet, **for a human to read** | free |
| `--email --dry-run --hunter-key K` | Prints the exact Hunter spend plan and the key's live balance | free |
| `--email --hunter-key K --hunter-budget 1000 --until-hunter-exhausted` | The live waterfall | **credits** |
| `--csv` | Writes one row per business, with provenance | free |

Every stage writes the state file after each row, and on re-run skips rows it has already done (`"site"`, `"linkedin"`, `"email"` keys). A crashed or closed session therefore resumes by re-running the same command. This happened once (8 Oct) and nothing was lost.

### 3.2 The Hunter gate (`icp.hunter_eligible`, 26 tests in `tests/test_icp.py`)

A Hunter call is made only when **all** of these hold:
- the account is `qualified`;
- the buyer is `qualified`, meaning in §3's closed list (founder, co-founder, owner, CEO, president, COO, executive director) directly or by corroboration;
- the buyer has a first and last name;
- the business has its own domain;
- no cheaper step has already found an address;
- no other row on the same domain has had a call this run.

Domain search (Hunter with no name) is off; Utah measured 32 calls for 1 email. Eligible rows are spent in this order: priority B before C, then evidence strength, then `review_count`, with a missing count ranked last. Every skipped row records its reason, which appears in the CSV's `hunter_gate` column.

### 3.3 Why the gate's inputs were clean: read every buyer before a live run

**This step is where most of the quality comes from, and it is manual.** Each larger batch brought *new* noise that passed the role regex as founder, owner or CEO. About 30 such "buyers" were caught in Houston, each of which would have cost a call:

- Page phrases: "Finally Feeling Like", "Executive Vice", "Pledge Class", "American Society", "Facts Accreditation Office".
- A web agency's JSON-LD `founder`: "Digital Innovation Solutions".
- A business name glued to a person: "Intra-V Samer Faysal", "Gameday Clayton".
- Edge words: "Story Betty Rogers", "Zoom Jessica Fields", "Farrah Louviere With".
- A repeated token: "Johanna Johanna Chaidez".
- **LinkedIn owners of a different business.** "Owner at Brilliance Communications" was matched to Brilliance MedSpa, along with owners of an AC company, a CrossFit gym and an MLM. `icp.headline_foreign_tokens` now demotes these to `ambiguous`.

The fix loop, all free:
1. Run `--buyers` and read *every* qualified line. On 7 Oct only the qualified lines were read, and one Snov credit went on a person named "Reviews Plans".
2. Add the noise word to `_NOT_A_NAME` (never a name) or `_EDGE_NOISE` (stripped from either end).
3. Run `--website --force`. It re-parses from the §7 cache; only previously errored sites are re-fetched.
4. Run `--qualify`, then `--buyers` again.

**Some wrong buyers no rule can catch.** In Houston: a "President" who presides over a billing company, and the president of Baylor College of Medicine shown on a university clinic's page. Hold such a row out by hand so the gate never sees it. This is how that was done, and the reason ends up in the CSV:

```python
# from backend/, PYTHONIOENCODING=utf-8
import sys; sys.path.insert(0, "scripts"); import spike_medspa_ny as s
p = s.Path("data/spike/<batch>.json"); rows = s.load_state(p)
why = {"<Business name exactly>": "manual review: buyer is president of <other org>"}
for r in rows:
    if r["name"] in why:
        c = s.best_candidate(r)
        r["email"] = {"person": c.name, "person_source": c.source, "email": None, "source": None,
                      "attempts": [{"source": "hunter", "skipped": why[r["name"]]}]}
s.save_state(p, rows)
```

### 3.4 Domain handling (`business_domain`)

- Booking-platform tenants return no domain (`*.as.me`, `*.zoca.com`, `*.janeapp.com`, `*.airoapp.ai`, …).
- A chain's store-locator subdomain (`locations.livehydrationspa.com`) is reduced to the registrable domain, but only under generic TLDs.
- If a new tenant platform appears in `--dry-run` as a shared domain, add it to `_PLATFORM_HOSTS`.

## 4. What to build before any credit is spent

### 4.1 Multi-key rotation (`--hunter-keys`)

- Add `--hunter-keys 3,1,4,2`: an ordered list, replacing or alongside `--hunter-key`.
- **Order by soonest reset first.** An unused search is lost at reset, so spend the expiring key first.
- At the start, print each key's live balance (`hunter_balance`, the free `/v2/account` endpoint).
- `HunterSpend` holds the list and an index. When `Quota.note("hunter", 429|402)` stops Hunter, move to the next key, clear `quota.stopped["hunter"]`, and print the switch.
- `--until-hunter-exhausted` stops only when the *last* key is exhausted.
- The Hunter `cache_key` excludes the API key on purpose: a cached "not found" is a fact about the query, so rotation never re-pays for one.
- Add a test: a sequence of statuses (200, 429 on key A, then 200) must make the next call go out on key B.

### 4.2 The master export (`--master`)

- Add a `--master` mode that reads a batch CSV (or state) and **appends** to `../texas_medspa_leads_master.csv`.
- Use exactly the current columns plus `lead_tier`. The header is the one already in the file.
- **Tier rules** (they reproduce the existing 86 rows exactly):
  - `email`: an `email` is present and `email_verification != "accept_all"`.
  - `linkedin`: otherwise, a `linkedin_url` is present and `buyer_verdict == "qualified"`. If the row's only email was `accept_all`, **blank** `email`, `email_person`, `email_source`, `email_score` and `email_verification` in the master row. The address stays in the batch CSV and the state file (§10.1: never discard), but it must never appear on the master list. Two current rows are like this.
  - anything else is not written.
- **Dedupe before appending**, on `maps_url`, then on (domain of `website`, `buyer_name`). If a row is already present as `linkedin` and now qualifies as `email`, upgrade it in place. That is the one allowed rewrite: evidence only moves up.
- **The `email` tier includes 5 rows whose buyer is `unknown` or `ambiguous`** (for example, the Prospeo address for Avante's Mary Ann Urban). The operator kept these when shown them on 8 Oct, so keep the same behaviour for new rows. Free sources (the business's own site) and the ungated vendors produce such rows; Hunter never does, because of the gate.
- After appending, check that the master holds 0 `accept_all` rows: `email_verification == "accept_all"` must never appear.

### 4.3 More Texas metros

Add these to `TEXAS_METROS` next to `HOUSTON_TILES`, written in the same shape. **Every tile list is a hypothesis.**

- **dfw.** Dallas areas: Uptown, Downtown, Highland Park, Preston Hollow, Lakewood, Oak Lawn, Bishop Arts. Fort Worth areas: Downtown, West 7th, TCU, Near Southside. Suburbs: Plano, Frisco, McKinney, Allen, Richardson, Addison, Irving, Southlake, Grapevine, Colleyville, Keller, Arlington, Mansfield, Flower Mound, Denton, Rockwall, Prosper.
- **san_antonio.** Downtown, Alamo Heights, Stone Oak, The Dominion, Medical Center; New Braunfels, Boerne, Schertz, Helotes.
- **austin.** Downtown, South Congress, Westlake, The Domain, Mueller; Round Rock, Cedar Park, Georgetown, Lakeway, Bee Cave, Pflugerville, Kyle.

`--discover` for a new metro must pass `--exclude data/spike/medspa_tx_houston.json` (the whole Houston pool), plus every earlier metro's pool.

## 5. The arithmetic: what 170–180 storable emails need

Measured in Houston (855 rows processed, out of a 1,937-business pool):

| Measure | Value |
|---|---|
| Rows that pass the gate | 16% of account-qualified rows |
| Hunter finder hit rate | **31%** (43 emails from 140 calls) |
| Searches charged | **1 per email found** (misses are free: 140 calls cost 46 searches) |
| Verifications charged | about 2 per email found |
| Hunter emails that are **not** accept-all | **65%** (28 of 43). All 15 accept-all addresses in Houston came from Hunter, and each still cost a search. |
| Free storable emails (the business's own site) | 13, about 1.5% of rows processed. These need no credit. |
| Where the eligible buyers came from | website crawl (free) 79% of Hunter calls; Serper LinkedIn 21% |
| Yield per Houston-sized pool | about **44 `email` rows + about 42 `linkedin` rows** (28 from Hunter, 13 free, 3 from other vendors) |

Live balances, checked 29 Oct with the free `/v2/account` endpoint:

| Key | Searches left | Verifications left | Resets |
|---|---|---|---|
| 3 | 3 / 50 | 6 / 100 | **1 Nov** |
| 1 | 35 / 50 | 69 / 100 | **2 Nov** |
| 4 | 33 / 50 | 65 / 100 | 6 Nov |
| 2 | 50 / 50 | 100 / 100 | 15 Nov |

**Keys 1 and 4 were spent by something outside these sessions.** On 7 Oct they had 49 and 50 left. Check the balances again before every live run, and never assume the table.

- **Now:** 121 searches, worth about 79 more Hunter `email` rows (at 65%), plus the free ones.
- **After the 1 and 2 Nov resets:** keys 3 and 1 return to 50 each. The full window to 15 Nov holds about 271 searches. **Spend keys 3 and 1 before they reset, then again after.**
- **The pool is the real constraint.**
  - About 130 more `email` rows means about **3 more Houston-sized pools**, at about 44 per pool. They would cost about 140 searches (46 per pool), which fits in the window.
  - All of DFW, San Antonio and Austin together are probably about 3 Houstons, so the target is just reachable *if* every Texas metro is worked through.
  - Houston itself is used up: its "Medical spa" rows and all of its account-qualifying categories are done.
  - If Texas runs out first, **stop and ask the operator** whether to try another state, or to loosen the buyer gate (medical directors). Do not decide either one alone (see the 8 Oct decision).
- **Accept-all costs cannot be avoided up front.** The finder only reports `accept_all` *with* the charged result, and no free Hunter endpoint shows a domain's catch-all status. Budget for about a third of charged searches producing addresses that never reach the master. The gate stays as it is.

**Serper is the second budget: 1,025 credits on 29 Oct.** Houston used about 1,000 for 855 rows. Ration it:
- Run `--qualify` **before** `--linkedin` and spend Serper only on account-qualified rows. Batch 3 did this and skipped 334 rows.
- Better still, which is not built: only on account-qualified rows **without** a qualified site buyer, ordered by `review_count`. Those are the only rows where LinkedIn can add a Hunter-eligible buyer.
- Keep a reserve of about 50 credits, and check the balance at `GET https://google.serper.dev/account` (header `X-API-KEY`).

## 6. Run order for one metro

Work from `backend/` with `PYTHONIOENCODING=utf-8`. Never run two scraping commands at once.

1. `docker compose up -d postgres redis` from the repo root, then wait for `pg_isready`. Postgres is on **5433**, and the §7 cache lives there.
2. Discover the metro:
   ```
   PROXY_REQUIRED_SOURCES="" uv run python scripts/spike_medspa_ny.py --discover --region tx --metro dfw --tiles 0 --synonyms 3 --limit 3000 --out ./data/spike/medspa_tx_dfw.json --exclude ./data/spike/medspa_tx_houston.json
   ```
   - **Pass `--tiles 0`.** The default is 3, which silently uses only 3 tiles.
   - Never re-discover into a pool file. A cached re-run returns fewer rows than the live run.
   - Read the metro-check output, which lists address cities outside the tile list. Keep those rows.
3. Slice the batches:
   - **b1:** `--slice --into ..._dfw_b1.json --size 1000` (category "Medical spa").
   - **b2:** `--slice --into ..._dfw_b2.json --size 1000 --exclude ..._dfw_b1.json --category "Skin care clinic,Medical clinic,Spa,Facial spa,Day spa,Laser hair removal service,Dermatologist,Wellness center,Health spa,Permanent make-up clinic,Esthetics service,Hair removal service,Health and beauty shop"`.
4. Run `--website` on the batch. Expect about 30% of "Medical spa" sites to name a person, and about 17% for the other categories.
5. Run `--qualify`. For a non-"Medical spa" batch, first keep only the account-qualified rows in a new file. The batch-3 "b3q" step did this:
   ```python
   q = [x for x in rows if x["icp"]["account"]["verdict"] == "qualified"]
   ```
6. Run `--linkedin` on that file (Serper; ration it per §5), then `--qualify` again.
7. Run `--buyers` and read every qualified line. Fix noise per §3.3, re-parse, re-qualify, and repeat until the list is clean. Hold out the wrong buyers by hand.
8. Run `--email --dry-run --hunter-keys 3,1,4,2`. Check the plan: no platform domain should appear, and no buyer that isn't a person. The operator's spend instruction stands (use the allowance fully), so there is no need to ask again before a live run, but **do** report the plan size.
9. Run the live email step:
   ```
   --email --hunter-keys 3,1,4,2 --hunter-budget 1000 --until-hunter-exhausted
   ```
   - Back up the state file first (`cp X.json X.pre_email.json`).
   - Watch the log for `network failure`. The run stops itself and leaves the row untried; re-run the same command to resume.
10. Run `--csv`, then `--master` to append to `texas_medspa_leads_master.csv`. Also refresh the full-row and with-email CSVs at the repo root if the operator still wants them.
11. Repeat for the next metro until the keys are exhausted or the pool is, then ask (§5).

## 7. Traps that cost time in these sessions

- **`ruff format .` from `backend/` reformats about 55 files you have no business touching.** Format only named files: `uv run ruff format scripts/spike_medspa_ny.py src/leadscraper/core/icp.py tests/test_icp.py`. It happened once, and the fix was `git checkout --` of the untouched files.
- The green bar is `uv run pytest` (781 passed on 8 Oct) plus `uv run ruff check .`.
- **Tomba allows 5 lookups a day** and RocketReach 3 a month; both were gone within minutes. **Snov** ran out of credits (402) in batch 2 after about 200 attempts that found 1 email. **Prospeo** ran out (429) in the same batch. Check them again before assuming any are live; their resets were around 23–24 Oct.
- **Hunter's charges show up late.** Key 3's balance dropped by 2 between runs with no calls made in between.
- **`hunter_balance` is deliberately uncached.** A balance is a fact about this moment, and replaying it from the cache would mislead.
- Background runs take a long time: the website crawl on 551 rows and the email run on 551 each took over an hour. Run them in the background, and re-run the same command if the window dies.

## 8. Report to the operator at the end

1. Rows discovered per metro, and the batch sizes.
2. Account and buyer splits.
3. Hunter calls made, searches charged per key, and the balances left.
4. Emails found, and **how many were accept-all** and so left out of the master.
5. Rows appended to the master, by tier, and the master's new total.
6. Serper credits used and left.
7. Any wrong buyers held by hand, and any new noise patterns fixed.

Add a dated note to `implementation.md` §8 with the numbers, and update the README's "things worth knowing" for `--hunter-keys` and `--master`, in the same change as the code.
