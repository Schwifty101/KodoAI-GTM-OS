-- Plan 5: one row per sheet row we have seen (tab, block, row_key); owner LinkedIn captured from the sheet.
alter table leads add column if not exists owner_linkedin text;

create table if not exists sheet_rows (
  id uuid primary key default gen_random_uuid(),
  tab text not null,
  block int not null,
  row_key text not null,
  lead_id uuid references leads(id) on delete set null,
  suppression_id uuid,
  sheet_row_no int,
  content_hash text,
  colour_seen text,
  colour_written text,
  written_at timestamptz,
  last_seen_at timestamptz,
  orphaned boolean not null default false,
  queue_state text check (queue_state in ('waiting', 'verified', 'failed')),
  created_at timestamptz not null default now(),
  unique (tab, block, row_key)
);
alter table sheet_rows enable row level security;
create policy operator_only on sheet_rows for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz');
