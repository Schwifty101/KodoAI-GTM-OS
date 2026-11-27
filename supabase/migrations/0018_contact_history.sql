-- Plan 9: contact_history ledger (one row per contact and round we mailed, recovered from Notion and the sheet or snapshotted from OS sends); leads.round and leads.history_id for recontact leads.
-- Applied by the owner only. Until then this table and these two leads columns are absent from the real database; code reads the ledger only when recontact_on is set.
create table if not exists contact_history (
  id uuid primary key default gen_random_uuid(),
  email text,
  domain text,
  business_name text,
  owner_name text,
  owner_title text,
  website text,
  city text,
  state text,
  subject text,
  vector text,
  round int not null default 1 check (round >= 1),
  first_sent_on date,
  last_sent_on date not null,
  date_basis text not null check (date_basis in ('exact', 'upper_bound')),
  touches_sent int check (touches_sent between 0 and 3),
  outcome text not null check (outcome in ('no_reply', 'auto_reply', 'replied', 'bounce', 'negative', 'opt_out', 'do_not_contact', 'disqualified', 'booked', 'client', 'unknown')),
  source text not null check (source in ('notion', 'sheet', 'os')),
  source_ref text,
  lead_id uuid references leads(id) on delete set null,
  created_at timestamptz not null default now(),
  check (email is not null or domain is not null)
);
create unique index if not exists contact_history_key on contact_history (source, coalesce(email, ''), coalesce(domain, ''), round);

alter table leads add column if not exists round int not null default 1;
alter table leads add column if not exists history_id uuid references contact_history(id) on delete set null;
create unique index if not exists leads_history_id_key on leads(history_id) where history_id is not null;

alter table contact_history enable row level security;
create policy operator_only on contact_history for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz');
