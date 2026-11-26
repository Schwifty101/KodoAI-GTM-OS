# Plan 9 design: recontact policy (2026-11-26)

Owner direction (approved): "emails can be reused every quarter". This document is design only. Nothing here is built, migrated or written to the real database. Facts below were read on 2026-11-26 with read-only queries (Supabase, the sheet tabs through `gtm/sheet.py`, the Notion tracker); no addresses or names are repeated.

## Intent
Today an address or company the OS has mailed, or that sits in `suppression`, is blocked forever. A named owner with a verified email is the scarcest thing the OS makes (14% of leads that reach enrich come out enriched, `2026-11-25-yield-aware-walk-design.md`; about 116 free Hunter credits were left on 2026-11-18). About 200 such contacts already exist from Batches 01-03 and the sheet. The owner wants a contact back in play about a quarter after its last send when it never answered, and never wants to re-mail anyone who said no, bounced or opted out.

## Goals
1. A contact is eligible again 60 days after its last send when the sequence ended with no reply of any kind and nothing else blocks it. 90 is the owner's "about a quarter", stored as a setting; the clock is per contact (rolling), not a calendar quarter.
2. Pre-OS history (Notion Batch01-03, sheet tabs) qualifies too, from recovered send dates, owner names and outcomes.
3. The suppression guarantee is never weakened: everything that blocks today still blocks. A block is lifted only by positive evidence (a clean outcome, an old enough date), never by missing data.
4. Reuse the pipeline as it is (verify, signals, select, review, draft, send). One new table, one new pass, one changed function.
5. Off by default; off is today's behaviour exactly.

## Non-goals and anti-goals
- Never recontact: bounce, unsubscribe or opt-out, not-interested, `do-not-contact`, any reply (positive, neutral, negative), booked, client, disqualified. An out-of-office reply is the only reply that does not block (it never stopped a sequence). `sheet-dropped` rows (red: the owner rejected the lead, never emailed) stay blocked.
- No edit or delete of any real `suppression` row, no new way for a code path to skip the check, no change to the `blocked_reason(lead, suppressed, contacted)` signature.
- No automatic start and no automatic send. Starting a new sequence is the owner's explicit act (the MedSpa rule "do not repeat a completed sequence unless Soban explicitly starts a new one"): switching `recontact_on` on, running Apply, then the usual Review approval, Draft and Send start.
- No change to email copy, angles or `MedSpa/` (parked: `docs/NEXT-email-strategy.md`; 0 positive replies in 218 sends). Round-2 text is whatever the draft pass writes.
- No change to footer defaults, no metrics page (Plan 6), no new paid source, no Google Places data.

## Facts (2026-11-26)
| Item | State |
|---|---|
| `suppression` | 522 rows, columns `id,email,domain,reason,created_at` only. 434 inserted 2026-11-10 (Notion), 88 on 2026-11-18 (sheet). Reasons (emails/domains): `notion-contacted` 201/204, `sheet-sent` 24/19, `sheet-dropped` 24/21, `do-not-contact` 11/12, `notion-bounce` 6/0. `created_at` is the import date, not a send date |
| OS sends | 0 real. 3 `sent` touches exist, all on `TEST_` leads from 2026-11-10 (test residue); `is_test_lead` already keeps them out of the ramp. `sending_on` is off, autopilot is on |
| `leads` | 866 rows, 66 numbered in batch 3. Only 3 of 266 suppression emails and 13 of 256 suppression domains match any lead: the pre-OS contacts are almost absent from `leads` |
| Notion Batch01 | 98 rows, Initial Sent 2026-08-04 to 08-29 (97 dated), Last Contacted up to 09-02. Status: Cadence Complete 80, Sent at Touch 2 12, Bounced 3, Disqualified 3. DNC 6 |
| Notion Batch02 | 89 rows, Initial Sent 09-02 to 10-07, Last Contacted up to 10-11. Cadence Complete 60, Sent at Touch 2 18, Bounced 6, Not Interested 4, Replied (out of office) 1. DNC 6 |
| Notion Batch03 | 32 rows, Initial Sent 10-10 to 10-12, DNC 0. Status breakdown not re-read (the Notion SQL allowance ran out); `docs/HANDOFF.md` says 30 sent, 2 bounced, no Touch 2 or 3 logged |
| Notion fields | Founder, Role, Company, Email, Website, HQ City, State, Initial Sent, Last Contacted, Touch, Status, Reply Type, First Reply, Do Not Contact, Subject, Email Body, Campaign Batch, Vector Used (Batch02-03). Person, company, site and role are on all 219 rows; email and body on 218. No Google place id |
| Sheet tabs (Texas, Newyork, Utah) | business, maps_category, metro or city, website, buyer_name, buyer_role, linkedin, email, maps_url (place id on 97 of 97 Texas and 200 of 200 Newyork rows, 18 of 44 Utah rows), buyer_verdict (Texas). Green = owner marked sent, red = dropped. No dates, outcomes or touch counts. The OS now paints these colours too, so import-time `sheet_rows.colour_seen`, not live colours, says what the owner marked |
| Callers of "already contacted" | All go through `gtm/select.py:_blocklists`: select, draft, redraft, send (`schedule_approved`, `send_scheduled`), `sheet_verify`, `sheet_queue`, the `verify-sheet` CLI preview. `run_followups` reads only the suppression half. `enrich` does not check (known) |

## CAN-SPAM and deliverability
- Commercial email to businesses is covered by CAN-SPAM (FTC guide, read 2026-11-09 per `docs/HANDOFF.md`; not re-checked today, not legal advice). It requires a postal address, a working opt-out and honouring opt-outs; the figure in the handoff is up to $53,088 per email. Re-mailing is not itself banned.
- The footer values are blank by owner decision and code never invents or blocks on them. A second or third email to the same person with no opt-out line repeats that exposure and the person has had longer to complain. The control is an owner gate before `recontact_on` (Owner decision 5), not code.
- Opt-outs are forever by construction: `opt-out reply`, `not-interested`, `do-not-contact`, bounce reasons are not in the cooldown set, and any reply stops the contact.
- Complaints are invisible: the Gmail API cannot show spam complaints (ledger ruling T14, `docs/HANDOFF.md` section 6); only bounces pause a mailbox (3% over 20 sends). A re-mailed non-responder is plausibly more likely to complain than a first-time recipient (judgment, not measured) and the sending domain was about three months old on 2026-11-11 (a session fact in the handoff). So recontact starts as small slices through the normal ramp, with the address re-verified first.
- Addresses age: 12 of 218 (5.5%) bounced at first send. The Enriched rule (valid, score >= 75) is unchanged, so a recontact address is Hunter-verified again before it can be selected.

## Constraints
Supabase Postgres only; `gtm/config.py` the only env reader; every paid call writes `cost_log`; lead identity stays a place id, unique globally; statuses unchanged; Send stays a separate explicit action; migrations are applied by the owner, never by code (migration 0015 precedent); the autopilot is live on the real database, so tests and verify scripts use `TEST_` rows and never wildcard-delete real prefixes.

## Approaches considered
| | A: expire by date | B: `release_after` on `suppression` | C: ledger plus one choke point (recommended) |
|---|---|---|---|
| Idea | Treat `notion-contacted` and `sheet-sent` rows as expiring 60 days after `created_at` | New nullable column; UPDATE real rows | New table `contact_history`; `_blocklists` lifts a key only with a clean ledger row |
| Why not | `created_at` is the import date (2026-11-10), so everyone returns on 2027-02-08; Disqualified and neutral-reply rows share the reason and would return; no names to mail | UPDATE of 448 real rows (owner gate); still no names or outcomes | One new table and migration |

Fail-closed core of C: with no ledger row, no flag or any error, nothing is lifted. Re-entry is a second decision (how a released contact gets a second sequence):
- Reset the same lead row: needs `touches.round` and a changed unique key; about 22 Python and 12 web call sites read touches by lead and touch number. Invasive.
- Archive then delete the touches: contradicts the MedSpa rule "a confirmed resend is added as new history, never erase the earlier send".
- **New lead row per round (recommended):** the old lead and its touches stay untouched; the new row carries `round` and a pointer to the ledger row. The whole pipeline sees a normal lead.

## Design
**Policy.** A contact (its email and domain keys) is released when `recontact_on` and its ledger outcome is `no_reply` or `auto_reply` and `last_sent_on + recontact_days <= today` and its round is below `recontact_max_rounds` and no suppression row with a non-cooldown reason shares any of its keys and no other ledger row on a shared key is unclear or recent. Cooldown reasons are exactly `notion-contacted` and `sheet-sent`; every other reason, including unknown ones, is permanent. For leads the OS sent itself: the contact is released when the lead is still `sent` (any reply, bounce, unsubscribe, suppression or booking changes the status and keeps it contacted forever), has no unsent touch, its last sent touch is old enough and its round is below the cap. `TEST_` and `REHEARSAL_` leads are never released.

**One choke point.** `_blocklists(db, today=None)` keeps its return type. With the flag off it runs today's code and never reads the ledger. With it on, `suppressed` is every suppression key minus `released_keys(...)`, and `contacted` is the sent-touch keys minus released leads. A ledger read error raises: passes abort rather than open. Every caller inherits it; none changes.

**Schema (migration 0018, applied by the owner).**
```sql
create table contact_history (
  id uuid primary key default gen_random_uuid(),
  email text, domain text,                  -- lowercase keys, as in suppression; webmail and booking domains never stored as domain
  business_name text, owner_name text, owner_title text, website text, city text, state text,
  subject text, vector text,                -- Touch 1 as sent, so a later round can vary the angle
  round int not null default 1 check (round >= 1),
  first_sent_on date, last_sent_on date not null,
  date_basis text not null check (date_basis in ('exact','upper_bound')),  -- upper_bound: a date on or after the true last send, never before
  touches_sent int check (touches_sent between 0 and 3),
  outcome text not null check (outcome in ('no_reply','auto_reply','replied','bounce','negative','opt_out','do_not_contact','disqualified','booked','client','unknown')),
  source text not null check (source in ('notion','sheet','os')), source_ref text,   -- 'Batch02', 'Texas'; no personal data
  lead_id uuid references leads(id) on delete set null,   -- 'os' rows: the lead that was mailed
  created_at timestamptz not null default now(),
  check (email is not null or domain is not null));
create unique index contact_history_key on contact_history (source, coalesce(email,''), coalesce(domain,''), round);
alter table leads add column round int not null default 1,
  add column history_id uuid references contact_history(id) on delete set null;
create unique index leads_history_id_key on leads(history_id) where history_id is not null;  -- one re-entry per ledger row
-- RLS: operator_only policy, same text as 0015
```
`suppression` and `touches` do not change. Settings (defaults in `gtm/settings_store.py` and `web/lib/settings.ts`): `recontact_on` false, `recontact_days` 60, `recontact_max_rounds` 3, `recontact_hunter_allowance_credits` 0.0 (a lifetime allowance like `import_hunter_allowance_credits`, bucket `hunter_recontact`; 0 means it cannot spend). A stored `recontact_days` or `recontact_max_rounds` below 1 falls back to the default (a zero would lift everything).

**Recontact pass** (`recontact [--limit N] [--confirm]`, worker kind, dry run by default; the dry run reads only and prints counts, the Hunter cost at 0.5 credit per email and the allowance left). Candidates: ledger rows without a spawned lead, plus OS leads in `sent` that are released. Oldest last send first. A candidate is skipped and counted, with a reason, when its title is not a decision-maker, it has no usable domain, the state is not US, the name says day spa or school, or a live lead (cleaned or later, not rejected) already has its domain or email (a twin). Apply needs `recontact_on`, `--limit`, and allowance: it verifies each email with the existing `verify_lead`, then inserts the new lead in its final status, `enriched` when verification passes, else `no_buyer` with the name kept; never `cleaned`, because autopilot would run enrich on it and spend credits finding an owner we already have. An OS-sent contact first gets a ledger snapshot row (`source 'os'`, outcome `no_reply`). New lead: `place_id = 'recontact:<ledger id>'`, `email_source 'history'`, `round = ledger round + 1`, `history_id`, tz from `lead_tz`, batch "Recontact <date>". From there autopilot runs signals (a fresh dated signal for the new quarter) and select; Review approval, Draft and Send are unchanged. The old lead and touches are never edited. A recontact lead the owner rejects stays out (one re-entry per ledger row).

**Identity.** `place_id` stays unique and never reused: pre-OS contacts have no Google place id, so the synthetic `recontact:` id follows the `domain:` precedent in `sheet_import.place_key`. The `clean` duplicate-domain rule keeps a later walk twin out, and the twin skip above keeps the reverse out.

**UI.** Settings "Recontact" group (four fields) and a Preview/Apply block using the Plan 8 guard (`recontact` joins `CONFIRM_KINDS`); `/leads` shows the round.

## What a backfill can and cannot recover
| Source | Recovers | Cannot |
|---|---|---|
| Notion Batch01-03 (219 rows) | Person, role, company, email (218), website, city, state, Touch 1 date (218), Last Contacted (218), touch reached, status, reply type, DNC, Touch 1 subject, angle (Batch02-03), body (read from Notion, not stored) | Google place id and category. Exact dates of Touch 2 and 3 (Last Contacted is hand-kept; Batch03 has no automations). Whether follow-ups went out after 2026-10-12 (nothing is logged after it). A reply the owner never logged. Whether the address is valid today or the person is still there |
| Sheet green rows | Business, category, city, website, buyer name and role, linkedin, email, place id (most rows) | Any send date, touch count, outcome (green only says sent). Only 24 emails and 19 domains are `sheet-sent` rows not already in Notion |
| `suppression` | Email or domain, reason, import date | Everything else |
| `leads` and `touches` | OS sends in full (none real yet) | Nothing pre-OS |

Rules for dates and outcomes (never earlier or looser than provable): `last_sent_on = max(Last Contacted, Initial Sent + 7 days)`, because the cadence is Day 0/3/7 with no Touch 4 and the follow-ups may have gone out unlogged (`date_basis exact` only when Last Contacted already is the later). A sheet-sent row has no date: its date is the `created_at` of its `sheet-sent` suppression row (2026-11-18, `upper_bound`) and its outcome is `unknown`, which never releases, until a Gmail cross-check or the owner says otherwise. Outcome precedence, strictest wins: DNC, bounce, negative or Not Interested, Disqualified, Call Booked, Client, any other reply, out of office (`auto_reply`), Sent or Follow-up Due or Cadence Complete (`no_reply`), anything else `unknown`. Rows with no send date get no ledger row and stay blocked. Resulting windows under these rules (first eligible day): Batch01 2026-11-09 to 12-04 (the earliest sends are already past 60 days), Batch02 12-08 to 2027-01-12, Batch03 2027-01-15 to 01-17, sheet-sent 2027-02-16, OS sends 60 days after the last touch of their sequence. Roughly 200 contacts are in the cooldown class by Notion status (92 + 79 + up to 30), before the Gmail check. The optional read-only Gmail check of the sending mailbox (scope already held, `gmail.readonly`) can give exact dates, find unlogged replies and bounces and clear the `unknown` sheet rows.

## Rollout and hard gates
1. Pure logic, settings, wiring and UI built and tested with no migration: flag off changes nothing (a parity test proves it).
2. Owner applies migration 0018.
3. Backfill dry run (counts per outcome and per eligibility week), owner reads it, then `backfill-contacts --confirm` writes the new table only.
4. Optional Gmail cross-check, owner's yes to read the mailbox and a second yes to write its results.
5. Read-only parity run on the real database: flag-off sets equal the old function; the flag-on report shows how many keys would lift, by reason, no addresses.
6. VM deploy with the flag off (queue idle; a deploy cancels a running job).
7. Owner sets `recontact_on`, the Hunter allowance and (Decision 5) the footer; first `recontact --limit N` Preview then Apply on a small N; then Review, Draft and Send as for any lead.
Never done by an implementing agent: any migration, real backfill, change to a real setting or suppression row, recontact Apply, Hunter, signals, draft or send, deploy, push.

## Assistant rulings recorded
Approach C with a new lead row per round; `suppression` untouched; fail closed on absent, failed or empty evidence; ledger read only when the flag is on; re-verification inside the pass and the lead created in its final status; no autopilot stage for recontact; `hunter_recontact` allowance defaults to 0; the owner-chosen days stay a setting; the +7 day bound is derived from the cadence, not measured.

## Owner decisions (max 5)
1. **Window and cap.** 60 days from the last send (your number), and at most 3 sequences per contact (the original plus two re-approaches). Recommend yes: a third unanswered sequence is where it reads as spam. The cap is my judgment, not a measurement; `recontact_max_rounds` changes it.
2. **Which outcomes come back.** Only "no reply" and out-of-office. Never any reply, bounce, opt-out, not-interested, DNC, disqualified, client, booked; `sheet-dropped` stays blocked. Recommend yes. Wrongly blocked contacts are fixed by hand in the database as today.
3. **Backfill dates.** Use Notion dates with the Day-7 bound, give sheet-sent rows the 2026-11-18 bound and `unknown` outcome, and allow a read-only Gmail check of the sending mailbox to give exact dates and clear them. Recommend yes to the Gmail check (it also finds replies Notion missed); without it the 24 sheet-sent emails stay blocked.
4. **Re-verify and pay for it.** Every recontact address is re-verified by Hunter at 0.5 credit each before it can be selected (the Enriched rule does not bend), from a separate allowance that starts at 0. Recommend verify just in time, a slice per batch, after checking the key balance with the free `GET /v2/account`; verifying all 200 at once would use most of the remaining credits.
5. **Footer and timing.** Set the opt-out line and postal address before the first recontact send, and switch `recontact_on` on only after the email strategy is decided. Recommend yes to both: the first recontact send is the first time the same person is mailed twice, and round 2 with the round-1 copy repeats the first round, which drew 0 positive replies in 218 sends.

## Left to the builder
Exact column names in the Notion CSV export, the Gmail query wording, report formatting, the Recontact card layout.

## 12. Owner answers (2026-11-26), these override the recommendations above
1. **Window: 60 days** from the last send (not 90); `recontact_days` defaults to 60. Rounds cap stays at 3.
2. **Backfill dates:** use the real Notion dates where Notion has them (Batch01-03, with the Day-7 bound). Rows with no recoverable date (the sheet-sent contacts) get a placeholder `last_sent_on` of 2026-11-18 (the sheet import date), outcome `no_reply`, so they become eligible 2027-01-17 (60 days later). This is the owner's call: it relaxes the fail-closed `unknown` rule for sheet-sent rows only; `sheet-dropped` (red) rows, every reply, bounce, opt-out and do-not-contact row stay blocked.
3. **No Gmail cross-check.** Task 7 is skipped.
4. Remaining decisions (re-verify with Hunter from a separate allowance starting at 0; opt-out line and postal address set before the first recontact send; `recontact_on` stays off until the email strategy is decided) stay as recommended.
