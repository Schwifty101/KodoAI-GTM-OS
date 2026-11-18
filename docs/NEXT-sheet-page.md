# Later: a `/sheet` page in the web UI

Deferred by the owner on 2026-11-17 until the OS is complete. Plan 5 ships Settings plus CLI only. Design: `docs/superpowers/specs/2026-11-17-plan5-sheet-import-and-manual-queue-design.md`.

What the page would do (all of it already works from the CLI reports):
- **Import dry run in the browser:** "Check sheet" shows per tab green, red, uncoloured, candidates, drops with reasons, and the Hunter credit cost; an "Import" button next to the allowance.
- **Sync changes:** rows whose email or owner changed in the sheet, with those skipped because the lead is already drafted; accept or ignore each.
- **Queue status:** today's rows waiting for ContactOut, verified and failed ones, credits spent; push a lead to the front or drop it.
- **Colour write-back:** preview of rows the OS would paint green or red, an apply button, and a log of what was painted.
- **Allowance and switches** in one place.

The web side needs its own `verify_*.mts` script, like `/scrape` and `/batches`.
