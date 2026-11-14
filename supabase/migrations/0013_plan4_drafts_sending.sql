-- Plan 4 (drafts and sending): drafts live in touches; the scheduler stamps send_at; held drafts keep their failed-check codes.
-- Touch statuses are free text; the set in use: drafted, held, edited, approved, scheduled, sending, sent, cancelled.
alter table touches
  add column if not exists send_at timestamptz,
  add column if not exists approved_at timestamptz,
  add column if not exists problems text[] not null default '{}';
alter table batches add column if not exists draft_instruction text;
-- ramp_from: the ramp counts sending days on or after this date (the owner sets it to today when unpausing after an auto-pause).
-- replies_checked_at: when the send tick last read replies for this mailbox (shown on the Follow-ups tab).
alter table mailboxes
  add column if not exists ramp_from date,
  add column if not exists replies_checked_at timestamptz;
