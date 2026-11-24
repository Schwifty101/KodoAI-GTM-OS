# Sheet guidelines

Follow these and the importer reads your marks exactly as you meant them.

## 1. Colours
- Only two colours mean anything: **pure green #00FF00 = sent**, **pure red #FF0000 = dropped**.
- Colour the **whole row** (column A to the last header column). A row with both colours counts as red.
- Never use these two colours for anything else.
- No other fills, no banded rows, no conditional formatting, no Table styling. Pastel greens, cream, blue and teal fills are noise and get cleared; banded rows (Format > Alternating colors) and conditional rules over data rows are deleted by the tool. Table styling is not: convert each Table to a plain range by hand.

## 2. Headers
- Row 1, and the first row of any second block, is the only header: **dark grey fill, white bold text**. Its first cell is `business` or `Company`.
- Names the importer reads (any case): `business`, `company` (name); `maps_category`; `website`; `buyer_name`, `buyer`; `buyer_role`, `role`; `linkedin_url`, `linkedin (confirmed)`, `linkedin (to check)`; `email`; `maps_url`; `city`, `metro`.
- One block per tab: one header, one continuous table. Utah's header is: `business, maps_category, website, buyer_name, buyer_role, linkedin_url, email, email_person, other_people, maps_url, city, fit, role_check, role_evidence, role_evidence_url, linkedin_to_check, email_type, email_status, email_source, notes`.
- Extra columns are kept in the sheet but ignored by the importer (it reads only the names listed above). The old second-block names (`Company`, `Buyer`, `Role`, `LinkedIn (confirmed)`, `LinkedIn (to check)`, `Metro`) still import if a sheet is not merged yet.
- A tab with a second block (Utah rows 20-46) is merged under block 1 by `sheet-format --confirm` (step F). Do this BEFORE the first import: row numbers change.

## 3. Rows
- One lead per row. One email per cell: if there are several, only the first is used.
- `website` holds the business site.
- Never put a registered agent or service-of-process name in `buyer_name`.

## 4. Queue tab
- The `Queue` tab belongs to the OS. The only thing you do there is paste an email into the `email` column.

## 4b. os_status column
- `os_status` (right of the table) is OS-owned: `sent`, `dropped` or `open`. Do not type in it; the OS rewrites it daily with the colours. Sort or filter on it to group rows. Sorting a data tab is safe: the OS finds rows by their `maps_url`/`website`, not by row number.

## 5. What the OS does with marks
- Green or red row becomes suppression (never contacted).
- Every uncoloured row, with or without an email, becomes an unvetted lead. Flow: `import-sheet --confirm`, then `clean --batch <id>`, then `verify-sheet --batch <id> --confirm` (leads with a sheet email; run before enrich), then `enrich --batch <id>` (the rest), then `signals`, `select`, `draft` as for any lead. Named leads enrich cannot resolve end `no_buyer` and feed the manual queue. Clean and signals decide ICP; nothing from the sheet skips them.
- A row with no maps_url and no website cannot be keyed and is skipped.
- The OS paints status colours back only when write-back is on, and never over a mark you made.

## 6. Tidy up
- Before you start: do not edit the sheet during the run, and the worker's sheet jobs must be off.
- `uv run python -m gtm.cli sheet-format` is a dry run (counts only, changes nothing). Read it first. It prints `BLOCKED: ...` and exits non-zero if a Table, a filter or merged cells sit where it would write, if a header is unknown, or if there are rows above the header.
- `sheet-format --confirm` first merges a tab's extra block under block 1 (Utah) and stops; run it again for the formatting steps. `--merge-only` and `--no-merge` pick one. `--tab Utah` limits it to one tab; `--sheet-id ID` rehearses on a copy of the sheet (not saved; `import-sheet`, `sheet-queue` and `sheet-paint` take it too).
- Safety: it saves a local snapshot under `.secrets/` first, then re-reads the sheet and prints FAIL (exit 1) if anything differs. The check compares cell values and pure green/red marks only. The merge moves cells with `cutPaste` (PASTE_NORMAL), which carries links, notes and formats along, but the check does not compare them. On FAIL restore from the xlsx backup or File > Version history.
- It cannot remove Tables. Per table: select it, Format > Convert to range (it refuses to merge a tab that still has one).
