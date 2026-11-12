-- Operating layer: owner-editable settings, the job queue the worker drains, and per-provider spend for the UI.
create table settings (
  key text primary key, value jsonb not null, updated_at timestamptz not null default now()
);
create table jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null, payload jsonb not null default '{}',
  status text not null default 'queued' check (status in ('queued','running','done','failed','cancelled','paused_budget')),
  run_after timestamptz not null default now(),
  started_at timestamptz, finished_at timestamptz,
  attempts int not null default 0, result jsonb, error text,
  created_at timestamptz not null default now()
);
create index jobs_status_run_after_idx on jobs(status, run_after);

-- Atomically takes one due queued job. Worker-side only (secret key).
create function claim_job() returns jobs language sql as $$
  update jobs set status = 'running', attempts = attempts + 1, started_at = now()
  where id = (select id from jobs where status = 'queued' and run_after <= now() order by run_after, created_at limit 1 for update skip locked)
  returning *;
$$;
revoke execute on function claim_job() from public, anon, authenticated;

create view spend_summary with (security_invoker = true) as
select provider,
  coalesce(sum(units) filter (where created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'), 0) as units_today,
  coalesce(sum(usd)   filter (where created_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'), 0) as usd_today,
  coalesce(sum(units) filter (where created_at >= date_trunc('month', now() at time zone 'utc') at time zone 'utc'), 0) as units_month,
  coalesce(sum(usd)   filter (where created_at >= date_trunc('month', now() at time zone 'utc') at time zone 'utc'), 0) as usd_month
from cost_log group by provider;

alter table settings enable row level security;
alter table jobs enable row level security;
create policy operator_only on settings for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz');
create policy operator_only on jobs for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz');
