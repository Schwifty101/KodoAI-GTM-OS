# Sheet guidelines

Follow these and the importer reads your marks exactly as you meant them.

## 1. Colours
- Only two colours mean anything: **pure green #00FF00 = sent**, **pure red #FF0000 = dropped**.
- Colour the **whole row** (column A to the last header column). A row with both colours counts as red.
- Never use these two colours for anything else.
- No other fills, no banded rows, no conditional formatting, no Table styling. Pastel greens, cream, blue and teal fills are noise and get cleared.

## 2. Headers
- Row 1, and the first row of any second block, is the only header: **dark grey fill, white bold text**. Its first cell is `business` or `Company`.
- Names the importer reads (any case): `business`, `company` (name); `maps_category`; `website`; `buyer_name`, `buyer`; `buyer_role`, `role`; `linkedin_url`, `linkedin (confirmed)`, `linkedin (to check)`; `email`; `maps_url`; `city`, `metro`.
- Utah block 2 uses `Company`, `Buyer`, `Role`, `LinkedIn (confirmed)`, `LinkedIn (to check)`, `Metro`. Other columns are ignored.

## 3. Rows
- One lead per row. One email per cell: if there are several, only the first is used.
- `website` holds the business site.
- Never put a registered agent or service-of-process name in `buyer_name`.

## 4. Queue tab
- The `Queue` tab belongs to the OS. The only thing you do there is paste an email into the `email` column.

## 5. What the OS does with marks
- Green or red row becomes suppression (never contacted).
- Uncoloured row with an email becomes a candidate.
- The OS paints status colours back only when write-back is on, and never over a mark you made.

## 6. Tidy up
- `uv run python -m gtm.cli sheet-format` is a dry run (counts only, changes nothing). Read it first.
- `uv run python -m gtm.cli sheet-format --confirm` applies it (`--tab Utah` for one tab). It saves your marks to `.secrets/sheet_marks_snapshot_*.json`, re-reads the sheet afterwards and prints FAIL (exit 1) if any mark changed.
- It cannot remove Tables. Per table: select it, Format > Convert to range.
