# Plan 5 design: Google Sheet import, colour write-back and the manual queue (2026-11-17)

Status: **approved and BUILT (2026-11-23). Later owner changes: all uncoloured rows (with or without an email) are imported as `scraped` leads and go through clean, verify/enrich, signals and select; Utah is one merged table; Hunter acceptance is `valid` and score >= 75.** Original text: draft for the owner's approval, nothing built. Source: the Plan 5 brainstorm of 2026-11-17 and the read-only recon of the real sheet. Facts are marked **Owner** (decided by the owner in the brainstorm), **Recon** (measured on the real sheet, 2026-11-17), or **My call** (mine, for the owner to check). Outline and background: `docs/superpowers/plans/2026-11-17-plan5-outline.md`; operating-layer design section 7 and calls 15.3, 15.4, 15.10, 15.11: `docs/superpowers/specs/2026-11-12-gtm-os-operating-layer-design.md`. This design supersedes the outline and calls 15.3 (service account) and the outline's "Out" item on sheet writes.

## 1. Intent

Before the OS, the owner worked leads in a Google Sheet "MedSpa" (tabs Utah, Newyork, Texas): scrape, verify with ChatGPT, find emails, send, then colour the row. That work must not be lost or repeated. Plan 5 does three things:

1. **Import** the sheet once, re-runnable: coloured rows become suppression, uncoloured rows with an email become leads that go through the normal pipeline.
2. **Sync** later edits in the sheet to the OS (one way, sheet to OS, for contact fields).
3. **Write back** colours (OS to sheet) so the sheet keeps showing which leads were used or ignored, and run the **manual queue**: a daily tab where the owner pastes ContactOut emails that the OS reads back, verifies and uses.

## 2. Goals, non-goals, anti-goals

**Goals**
- No past work lost: every green and red row ends up in suppression, so the OS never contacts them again.
- The 87 uncoloured rows with an email (Recon: Texas 53, Newyork 33, Utah 1) are evaluated like any scraped lead.
- The sheet stays a usable working surface: row colours reflect what the OS did.
- The ContactOut round trip costs the owner about 5 pastes a day and nothing else.

**Non-goals**
- Any change to scraping, enrichment finders, drafting or sending (Plans 3 and 4).
- A web page for the sheet (Owner: skip for now; see section 12).
- Sync from the OS to the sheet other than colours and the Queue tab (Owner).
- Gemini assistant window, Plan 6 metrics, a second mailbox.

**Anti-goals (a failure even if it technically works)**
- The OS reads a conditional-format shade or a tint as "sent" or "dropped" and suppresses live leads.
- Re-import reads a colour the OS itself wrote as the owner's mark and turns an OS "red" into a permanent suppression.
- A sheet edit changes a lead that is already drafted or sent.
- Any write to the real sheet or paid Hunter call before the owner's yes.
- Overwriting a colour the owner applied by hand.

## 3. Access (Owner decision, then My call on mechanics)

- **Owner:** the sheet is owned by `soban@kodoai.xyz`, the sending mailbox. The OS reads and writes as that account.
- **My call:** reuse the existing Gmail OAuth client in project `kodoai-gtm-os` (Desktop client, consent screen Internal, no 7-day refresh expiry). The Sheets API is enabled on that project (Owner, 2026-11-17). Add the scope `https://www.googleapis.com/auth/spreadsheets` through a **separate** token file `.secrets/token_sheets.json`, not by widening the Gmail token, so the Gmail token that sending depends on is not touched while sending is on hold. The VM gets the Sheets token from Secret Manager the same way it gets the Gmail token (a headless worker never opens a browser). Consent happens once on the Mac.
- No service account (Workspace orgs often block key creation; not checkable from the account the OS can use).
- The sheet id is a Setting, never in the repo.
- The Claude Sheets connector cannot see this sheet (it is signed in as a different account) and does not return formatting; it is not part of the OS.

## 4. What the sheet looks like (Recon, 2026-11-17)

| Tab | Data rows | With an email | Green | Red | Uncoloured with email / without |
|---|---|---|---|---|---|
| Utah | 45 | 44 | 39 | 4 | 1 / 1 |
| Newyork | 200 | 66 | 20 | 13 | 33 / 135 |
| Texas | 97 | 61 | 6 | 2 | 53 / 37 |

- Totals about 342 data rows, 171 with an email, 87 uncoloured with an email.
- **Header rows:** Utah row 1 and Texas row 1 and Newyork row 1 are headers (blue or tinted fill). **Utah has a second block** whose header is on row 20 (dark teal; columns `Company, City, Website, Fit, Buyer, Role, ...`), with no blank row above it and a different column set.
- Utah/Newyork block columns: `business, maps_category, website, buyer_name, buyer_role, linkedin_url, email, email_person, other_people, maps_url`. Texas adds `metro, email_verification, buyer_verdict` (shifted layout). Texas `email_verification` holds `valid` (30), `accept_all` (15), `VERIFIED` (1): an earlier ChatGPT or Hunter check. It is a hint only; the OS verifies itself.
- Utah second block (header row 20, read live by the importer): the email is in column L, with the owner's LinkedIn in column J or K depending on the row (the builder maps by header text, not position). Webmail addresses (a `Personal (Gmail)` address published on the site) count as emails and go through the normal Hunter rule. Column M `Personal (Gmail)` type, column N a Gmail status text (`Published on site (Gmail), not verified`, `Not found`, verified), backed by a cream, pastel-red or pastel-green tint. No maps URL.
- **Owner decision 2026-11-18: one block per tab.** `sheet-format` step F merges Utah's block 2 under block 1 (rows 20-45, no blank row, no second header) under the unified 20-column header (`MERGE_TARGET` in `gtm/sheet_map.py`: block 1 names, then city, fit, role_check, role_evidence, role_evidence_url, linkedin_to_check, email_type, email_status, email_source, notes). Block-2 columns move by header alias with cutPaste (values, links, formats, marks move together); the merge is verified cell by cell and snapshotted first. Do it before the first import (row numbers change). The importer reads only the HEADERS names (`city`, `linkedin_to_check` and the block-1 names); the other new columns are kept and ignored. Old block-2 names still import on an unmerged sheet.
- Newyork: columns O to Z hold notes and 15 merged cells; a conditional-format rule over A:Z paints about 1,260 cells pastel green. The mapping stops at column J.
- 5 cells hold more than one email address.
- Newyork has 14 rows with a "service-of-process" registered-agent name as buyer.

## 5. Colour rule (Owner)

- **Pure green `(0,1,0)` in any cell of a row = sent. Pure red `(1,0,0)` in any cell = dropped.** Every other fill (pastel green, pastel red, cream, blue, teal, banding) means nothing. Blue and teal are headings (Owner).
- Read colours from the Sheets API field `userEnteredFormat.backgroundColor`, never `effectiveFormat`, so conditional formatting cannot create a mark.
- A row with both green and red is treated as red (dropped wins; My call).
- The Gmail-status tints in Utah's second block are not colour signals; the status **text** is read as an informational note on the lead.

## 6. Import (Owner decisions)

- **Green row -> suppression** with reason `sheet-sent`; **red row -> suppression** with reason `sheet-dropped`. Suppression only, no lead rows (Owner). Entries carry the email(s) and the domain of the row, so the existing "already contacted" check catches both.
- **Every uncoloured row, with or without an email -> a lead with status `scraped`** (Owner correction 2026-11-18: all uncoloured rows are unvetted). A row with no key (no maps_url, no website) is skipped `no_key`; the dry run prints `no email: N` per tab. Flow: `import-sheet --confirm` -> `clean --batch <id>` -> `verify-sheet --batch <id> --confirm` for leads with a sheet email (run BEFORE enrich so enrich does not re-search them) -> `enrich --batch <id>` for the remaining `cleaned` leads (usual finders; a sheet name and title are used as a saved name) -> `signals`/`select`/`draft` as for any lead. Named leads enrich cannot resolve end `no_buyer` and feed the manual queue (section 8). Clean and signals decide ICP; nothing from the sheet skips them.
- Identity: Google place id from `maps_url` when the row has one (Texas, Newyork), else the synthetic key `domain:<domain>` in the existing unique `place_id` column (call 15.4). A real id replaces it later.
- Multi-email cells are split. The first address that passes verification is used; the rest are kept in the lead's notes only if the builder finds a place (My call: optional).
- Registered-agent "owners" (the 14 Newyork rows) are ignored as buyer names: the lead keeps no owner and goes to the normal enrich route.
- The sheet's owner and email columns pre-fill `owner_name`, `owner_title`, `owner_email` and `email_source = 'sheet'` with `email_verified = false`. The lead is `enriched` only after the OS's own Hunter verification passes (`valid`, score >= 75; `accept_all` and `webmail` fail until measured).
- **Suppression keys (checked in code: `blocked_reason` in `gtm/select.py` matches a lead's email, its email's domain and its website domain against one set of lowercase emails and domains; the `suppression` table already has `email` and `domain` columns, so no table change):** a suppression entry for a sheet row holds the exact email(s) and the **website** domain. **Never** put a webmail domain (`gmail.com`, `yahoo.com`, `outlook.com` and similar) in the `domain` column: the matcher also compares the email's own domain, so it would block every address at that provider. A row with no email and no website domain (nothing to match) is reported in the dry run and skipped.
- Statuses and gates stay as in CLAUDE.md. Failed leads stay `no_buyer`, keeping the saved name.
- **Every run is a dry run** that prints, per tab, what it would add (suppression entries, leads, rows skipped and why, credits needed). It writes only with `--confirm`.

### Field map (Owner, final 2026-11-17)

Only these sheet fields are read; every other column is ignored.

| Sheet field | Lead column |
|---|---|
| `business` / `Company` | `name` |
| `maps_category` | `category` (and `categories`, which clean uses) |
| `website` | `website`, `domain` derived |
| `buyer_name`, `buyer_role` | `owner_name`, `owner_title` |
| `linkedin_url` | **`owner_linkedin`** (new nullable text column) |
| `email` | `owner_email`, `email_source='sheet'` |
| `maps_url` | `place_id` (parsed); none -> `domain:<domain>` |
| Utah block 2 `City`; Texas `metro` | `city` |
| tab name (Utah, Newyork, Texas) | `state` (UT, NY, TX; My call, helps the tz backfill) |

Ignored: `email_person`, `other_people`, Texas `email_verification` and `buyer_verdict`, Utah block 2 Fit, confirmation, evidence, email type and Gmail status, Newyork columns O to Z.

## 7. Sync (Owner: "syncing as well", then "one way, sheet to OS")

- Each imported row is tracked in a new table (section 10) by tab, block and row key (place id or `domain:`). The importer re-reads the sheet and compares each tracked row with what it stored.
- **Contact fields sync sheet -> OS:** email, buyer name, buyer role, LinkedIn (`owner_linkedin`), website. A changed email goes back through verification (costs credits, inside the import allowance, or the daily cap after the import is done).
- **Frozen once `drafted` or later:** the sheet never changes such a lead. The run prints the difference in its report.
- **New colours add suppression only.** A row that turns green or red since the last run adds a suppression entry. The sheet never removes a suppression entry; a wrongly suppressed lead is fixed in the database (CLAUDE.md).
- Rows are matched by key, not by position. If the owner changes a row's domain or Maps URL, the importer treats it as a new row and reports the old one as orphaned (My call: report only, no delete).

## 8. Manual queue (Owner decisions, My call on layout)

- **Selection (call 15.11):** named-but-no-email leads, ordered by named owner, LinkedIn URL present, then review count and rating descending. Pool: Texas and Newyork uncoloured rows with a named buyer and no email, plus the Houston leads saved as named-but-no-email (those already have DB rows; sheet rows without a DB lead are imported as `scraped` leads first). A lead whose pasted email fails verification stays `no_buyer` and is **never re-queued**. **Sheet-only rows (My call):** an uncoloured Texas or Newyork row with a named buyer and no email is turned into a lead by the queue job when it is picked: inserted as `scraped`, put through `clean`, and if it passes set to `no_buyer` with the saved name (the owner's ContactOut paste is its email source, so the paid enrich finders are not run on it). It gets a `sheet_rows` entry. Sheet rows have no review count or rating, so they sort after DB leads that have them.
- **The tab:** a new `Queue` tab in the same sheet. One row per lead: business, owner name, domain, LinkedIn search link, an empty `email` column for the owner, and an OS-owned status column (`waiting`, `verified`, `failed`) plus a hidden lead id.
- **Daily job (Owner: automatic each morning):** a worker job tops the tab up to **5 waiting rows** (a Setting), reads pasted emails, verifies each (0.5 Hunter credit, through the budget gate), enriches the lead if it passes, and removes finished rows at the next write. Failed leads stay `no_buyer`.
- Queue rows are matched by the lead id in their own row, so sorting or filtering the tab is safe. An email pasted into a row whose lead is no longer `waiting` (already removed, verified or failed) is ignored and listed in the run report. Each run reads the tab first (to keep pending pastes), then rewrites it (waiting rows plus new ones).
- A Texas `email_verification = valid` hint never skips Hunter verification.
- The tab is the whole interface; there is no web page.

## 9. Colour write-back (Owner decisions)

- The OS paints **the whole data row, columns A to J**, with pure green or pure red:
  - **Green:** the lead's Touch 1 was sent.
  - **Red:** the lead was ignored: rejected by clean, ended `no_buyer`, a pasted email failed verification, suppressed, bounced, unsubscribed, or replied "not interested".
  - **No colour:** `scraped`, `signalled`, `selected`, `drafted` (still in play).
- The colour follows the lead's state: a retried `no_buyer` that becomes enriched loses its red.
- **The OS never overwrites a colour the owner applied.** It records each colour it writes in the tracking table, so a later read tells the OS's own paint from the owner's. The importer creates suppression only from colours it did not write.
- **Whose paint is it (My call):** a row counts as the OS's own only if every cell A to J still has the colour recorded in `colour_written`. Any other state is the owner's. Consequences: if the OS wants to paint a row that already shows an owner mark, it does not (the owner's mark wins); if the owner clears or changes an OS paint, the OS leaves it and repaints only after the lead's state changes again and the row is no longer owner-marked; if the owner recolours an OS-painted row by hand to the same colour, the two cannot be told apart, which is harmless because the DB state already agrees (a known ceiling).
- Write-back covers **only leads that have a `sheet_rows` entry** (imported from the sheet or pulled into the queue). It never appends rows for scraped leads.
- A switch (`sheet_writeback_on`) turns write-back off.
- The **first real write to the sheet is a hard gate**: the owner sees a preview (rows and colours) and says yes. Writes are batched `batchUpdate` calls, one per run.

## 10. Data (My call; needs one additive migration, hard gate)

One new table, for example `sheet_rows` (additive, RLS operator-only like the others): `id`, `tab`, `block`, `row_key` (unique with tab and block), `lead_id` (nullable), `suppression_id` (nullable), `sheet_row_no`, `content_hash` (of the mapped fields), `colour_seen` (`green`, `red`, `none`), `colour_written` (`green`, `red`, `none`), `written_at`, `last_seen_at`, `orphaned`. The same migration adds one nullable column, `leads.owner_linkedin text` (Owner). No other change to `leads`, to status checks or to `suppression`. Per-tab and per-block column mappings are **data** in a small file or table the builder chooses (My call: a Python data file under `gtm/data/`, since the layout is fixed and versioned), not hard-coded in the importer.

## 11. Settings, jobs, budget

- **Settings (mirrored in `web/lib/settings.ts`):** `sheet_id` (text), `sheet_queue_size` (5), `sheet_queue_on` (morning job switch, off until the owner turns it on), `sheet_writeback_on` (off by default), `import_hunter_allowance_credits` (one-off).
- **Import allowance (Owner):** a **separate one-off Hunter allowance for the import**, not the daily cap. The dry run reports the credits needed (about 25 to 40 estimated, to be measured) and the owner confirms the number before any run. The queue's daily verification uses the normal daily Hunter cap (`cap_hunter_credits_day`). Every verification still writes a `cost_log` row with the lead and a note that marks it as import spend (`require` then `log_cost`, `gtm/budget.py`). **My call:** the allowance is its own bucket checked by `require` (a small addition to `gtm/budget.py` is allowed); import spend does not count toward the daily cap, and the daily-cap check is unchanged for everything else. The allowance is a lifetime total, not per day.
- **CLI:** `import-sheet [--tab T] [--confirm] [--allowance N]`, `sheet-queue [--confirm]`, `sheet-paint [--confirm]` (preview then apply the write-back). The worker runs the daily queue job like `walk` and `check-drafts` (route through `gtm.cli`).
- **Secrets:** the Sheets token and, for the VM, its Secret Manager copy; never printed or committed.

## 12. Deferred

A `/sheet` page in the web UI (import dry run and import button, sync changes with accept or ignore, queue status and reorder, colour write-back preview and log, one place for the allowance and switches) is **deferred until the OS is complete** (Owner). Noted in `docs/NEXT-sheet-page.md`. Everything it would do already works from Settings plus the CLI reports.

## 13. Constraints

US only. No day spas. `place_id` is globally unique. A signal needs a source URL and a date (nothing here invents one). Suppression and "already contacted" are checked before every draft and send. Footer values stay empty by default. Rehearsal rows use the prefix `REHEARSAL_`, never `TEST_`. Tests never touch the real mailbox row or the real sheet: sheet tests use fixtures built from the Recon shapes (the two Utah blocks, the 14 registered-agent rows, multi-email cells) and a fake Sheets client. One pytest process at a time. Sending stays on hold; no real sends.

## 14. Hard gates (stop and ask the owner)

Applying the migration; the first consent and storing the Sheets token in Secret Manager; any write to the real sheet (the first colour paint, the first Queue-tab write); any paid call (Hunter verification, Gemini beyond tests); deploying to the VM (queue idle first); merging to `main`.

## 15. Left to the builder

Module split (placeholders: `gtm/sheet.py` client and colour parsing, `gtm/sheet_import.py`, `gtm/manual_queue.py`), the exact mapping file format, the block detector (a row whose first cell is `business` or `Company`), the allowance accounting, the Queue-tab column order, how multiple emails per cell are kept, and the test fixtures. Build method, agent preamble and gates follow outline section 6.
