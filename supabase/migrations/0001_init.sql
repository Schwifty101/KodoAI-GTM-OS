-- GTM OS schema. Single operator; secret key bypasses RLS, the UI uses the operator's login.
create table batches (
  id uuid primary key default gen_random_uuid(),
  name text not null, city text, state text, query text,
  created_at timestamptz not null default now()
);
create table mailboxes (
  id uuid primary key default gen_random_uuid(),
  address text not null unique,
  daily_cap int not null default 40,
  enabled_on date,
  paused boolean not null default false,
  paused_reason text
);
create table leads (
  id uuid primary key default gen_random_uuid(),
  place_id text not null unique,
  name text not null, website text, domain text, address text, city text, state text, category text,
  rating numeric, review_count int,
  owner_name text, owner_title text, owner_email text, email_source text, email_verified boolean,
  signal jsonb,
  vector text check (vector in ('conversion_recovery','capacity','rebooking_retention')),
  signal_led boolean not null default false,
  approved boolean not null default false,
  status text not null default 'scraped' check (status in ('scraped','cleaned','rejected','enriched','no_buyer','signalled','selected','drafted','sent','replied','booked','bounced','suppressed','unsubscribed')),
  reject_reason text,
  mailbox_id uuid references mailboxes(id),
  batch_id uuid references batches(id),
  created_at timestamptz not null default now()
);
create index leads_status_idx on leads(status);
create index leads_batch_idx on leads(batch_id);
create index leads_domain_idx on leads(domain);
create table touches (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references leads(id) on delete cascade,
  touch_no int not null check (touch_no in (1,2,3)),
  status text not null default 'drafted',
  gmail_draft_id text, gmail_thread_id text,
  scheduled_for date, sent_at timestamptz, outcome text,
  unique (lead_id, touch_no)
);
create table suppression (
  id uuid primary key default gen_random_uuid(),
  email text, domain text, reason text,
  created_at timestamptz not null default now(),
  check (email is not null or domain is not null)
);
create index suppression_email_idx on suppression(email);
create index suppression_domain_idx on suppression(domain);
create table cost_log (
  id uuid primary key default gen_random_uuid(),
  provider text not null, units numeric not null, usd numeric,
  batch_id uuid, lead_id uuid, note text not null default '',
  created_at timestamptz not null default now()
);
alter table batches enable row level security;
alter table mailboxes enable row level security;
alter table leads enable row level security;
alter table touches enable row level security;
alter table suppression enable row level security;
alter table cost_log enable row level security;
create policy operator_all on batches for all to authenticated using (true) with check (true);
create policy operator_all on mailboxes for all to authenticated using (true) with check (true);
create policy operator_all on leads for all to authenticated using (true) with check (true);
create policy operator_all on touches for all to authenticated using (true) with check (true);
create policy operator_all on suppression for all to authenticated using (true) with check (true);
create policy operator_all on cost_log for all to authenticated using (true) with check (true);
