-- Plan 3a: tile coverage for the metro walk, batch number and time zone on leads. Additive only.
create table coverage (
  id uuid primary key default gen_random_uuid(),
  seq int not null,
  metro_rank int not null,
  metro text not null,
  state text not null,
  tile text not null,
  status text not null default 'pending' check (status in ('pending','running','done','failed')),
  places_found int,
  new_leads int,
  saturated boolean not null default false,
  queries_run int,
  scrape_batch_id uuid references batches(id),
  error text,
  started_at timestamptz,
  scraped_at timestamptz,
  unique (metro, state, tile)
);
alter table coverage enable row level security;
create policy operator_only on coverage for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz');

alter table leads add column batch_no int, add column tz text;
create index leads_batch_no_idx on leads (batch_no);
