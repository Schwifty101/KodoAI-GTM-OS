-- claim_job ignores jobs whose payload carries the test marker unless the caller asks for them, so a live worker never steals a test's job.
create or replace function claim_job(include_test boolean default false) returns jobs language sql set search_path = public, pg_temp as $$
  update jobs set status = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now()
  where id = (select id from jobs where status = 'queued' and run_after <= now() and (include_test or not jsonb_exists(payload, 'test')) order by run_after, created_at limit 1 for update skip locked)
  returning *;
$$;
revoke execute on function claim_job(boolean) from public, anon, authenticated;
drop function claim_job();
