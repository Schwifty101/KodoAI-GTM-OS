# Parked task: finalise the email copy and angle strategy

Status: **parked by the owner on 2026-11-12.** Come back to this when the strategy for the ongoing Batch03 is finalised (Batch03 is still the live Notion log until about 100 unique sends). Not part of the OS build brainstorm.

## What to finalise
1. The instruction documents for email drafting: `MedSpa/` (source of truth), the condensed copies `gtm/data/draft_prompt.md` and `gtm/data/signal_prompt.md`, and the mechanical checks in `gtm/draft.py` (`check_draft`).
2. The angles (today: vectors `conversion_recovery`, `capacity`, `rebooking_retention`; lanes signal-led vs relevance-led) and how to adjust them from data, not from opinion.
3. Owner's stated copy requirement (2026-11-12): emails must be very simple and easy to understand, still following the `MedSpa/` guidelines.

## Facts to start from
- Sending history Batch01-03: 218 Touch 1 sends, 12 bounces (5.5%), 4 negative replies, 2 out of office, **0 positive**. Nothing was logged after 2026-10-12 (`docs/spikes/sending_history.md`).
- Website-only evidence gave 0 of 6 dated signals, so most leads are relevance-led with thin personalisation (`docs/spikes/signals_dry_run.md`).
- Open question put to the owner and not yet answered: why 0 positive replies in 218 sends (angle, list, or something else)?

## Needed from the OS before the strategy can be data-driven
- The angle (vector and lane) stored on every draft, so response rate can be compared per angle.
- Response rate and bounce rate per batch and per lead on the Metrics page.
- Editing: per-draft edit of subject, opener and body; a bulk "rewrite with this instruction" using Gemini with a before/after preview, with the mechanical checks re-run after every rewrite.

## Where this is tracked
`docs/HANDOFF.md` section 9 (open items) points here.
