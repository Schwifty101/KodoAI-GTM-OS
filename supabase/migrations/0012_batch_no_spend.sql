-- Plan 3b Task 3: spend per batch of 100 (leads.batch_no). security_invoker so row level security on the underlying tables
-- still applies (same pattern as batch_metrics in 0006).
-- Counts only cost_log rows that carry a lead_id (join cost_log.lead_id = leads.id), summed by that lead's batch_no.
-- Cannot attribute: rows with no lead_id, notably scrape-time Apify, which is logged against the scrape run (cost_log.batch_id)
-- and never a lead; also any enrich/LLM call made without a lead context. Scrape spend stays in batch_metrics.apify_usd.
-- hunter/prospeo/serper are in units (credits/queries); gemini is usd.
create view batch_no_spend with (security_invoker = true) as
select l.batch_no,
  coalesce(sum(c.usd) filter (where c.provider = 'apify'), 0) as apify_usd,
  coalesce(sum(c.units) filter (where c.provider = 'hunter'), 0) as hunter_credits,
  coalesce(sum(c.units) filter (where c.provider = 'prospeo'), 0) as prospeo_credits,
  coalesce(sum(c.units) filter (where c.provider = 'serper'), 0) as serper_queries,
  coalesce(sum(c.usd) filter (where c.provider = 'gemini'), 0) as gemini_usd
from cost_log c join leads l on l.id = c.lead_id
where l.batch_no is not null
group by l.batch_no;
