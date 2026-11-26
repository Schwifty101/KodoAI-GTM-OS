-- Plan 6 (metrics), Task 1: event timestamps and daily cost. Additive only: two nullable columns, two triggers, one view; no backfill.
-- Outcomes and bookings stored before this migration keep a null timestamp: they still count in cohort rates and show as "undated" in the history.

-- touches.outcome_at: set to now() the first time outcome becomes non-null (insert or update), never overwritten.
-- A trigger covers the Python reply pass and the web setOutcome alike. The CASE (in parentheses, so plpgsql's IF does not
-- stop at its THEN) keeps old.* from being read on insert.
alter table touches add column outcome_at timestamptz;
create function touches_outcome_at() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.outcome is not null and new.outcome_at is null
     and (case when tg_op = 'INSERT' then true else old.outcome is distinct from new.outcome end) then
    new.outcome_at := now();
  end if;
  return new;
end $$;
create trigger touches_outcome_at before insert or update on touches for each row execute function touches_outcome_at();

-- leads.booked_at: same rule when status becomes 'booked'.
alter table leads add column booked_at timestamptz;
create function leads_booked_at() returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.status = 'booked' and new.booked_at is null then
    new.booked_at := now();
  end if;
  return new;
end $$;
create trigger leads_booked_at before insert or update on leads for each row execute function leads_booked_at();

-- cost_daily: cost_log grouped by UTC day, provider and scrape run. A row with only a lead_id follows its lead's batch_id;
-- a row with neither gets a null run_id. usd is 0 (not null) for credit-only providers. It does not filter test data:
-- the web code drops test runs, so the verify script can read its own TEST rows. security_invoker, as in 0006 and 0012, so row
-- level security on cost_log and leads still applies (a signed-out visitor sees nothing).
create view cost_daily with (security_invoker = true) as
select (c.created_at at time zone 'utc')::date as day, c.provider, coalesce(c.batch_id, l.batch_id) as run_id,
  sum(c.units) as units, coalesce(sum(c.usd), 0) as usd
from cost_log c left join leads l on l.id = c.lead_id
group by 1, 2, 3;
