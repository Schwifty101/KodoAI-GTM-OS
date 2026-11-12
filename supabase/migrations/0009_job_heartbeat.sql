alter table jobs add column heartbeat_at timestamptz;

create or replace function claim_job() returns jobs language sql set search_path = public, pg_temp as $$
  update jobs set status = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now()
  where id = (select id from jobs where status = 'queued' and run_after <= now() order by run_after, created_at limit 1 for update skip locked)
  returning *;
$$;
revoke execute on function claim_job() from public, anon, authenticated;
