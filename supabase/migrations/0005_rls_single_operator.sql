-- Task 16: signups may be open on the project, so "authenticated" is not enough. Only the operator's email passes RLS.
-- To change the operator, edit the email below in every policy.
do $$
declare t text;
begin
  foreach t in array array['batches','mailboxes','leads','touches','suppression','cost_log'] loop
    execute format('drop policy operator_all on %I', t);
    execute format($p$create policy operator_only on %I for all to authenticated using ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz') with check ((auth.jwt() ->> 'email') = 'soban@kodoai.xyz')$p$, t);
  end loop;
end $$;
