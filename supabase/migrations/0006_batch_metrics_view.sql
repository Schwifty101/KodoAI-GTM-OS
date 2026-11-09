-- Task 19: per-batch funnel and cost. security_invoker so row level security on the underlying tables still applies
-- (a plain view runs with its owner's rights and would expose every row to a signed-out visitor).
-- Funnel columns count leads that reached each stage; hunter is in credits because no Hunter plan is priced yet.
create view batch_metrics with (security_invoker = true) as
with cost as (
  select batch_id,
    sum(usd) filter (where provider = 'apify') as apify_usd,
    sum(units) filter (where provider = 'hunter') as hunter_credits,
    sum(units) filter (where provider = 'serper') as serper_queries,
    sum(units) filter (where provider = 'groq') as groq_tokens
  from cost_log where batch_id is not null group by batch_id
),
agg as (
  select l.batch_id,
    count(*) as scraped,
    count(*) filter (where not (l.status = 'scraped' or (l.status = 'rejected' and coalesce(l.reject_reason, '') <> 'operator'))) as cleaned,
    count(*) filter (where l.owner_email is not null and l.email_verified) as enriched,
    count(*) filter (where l.signal is not null) as signalled,
    count(*) filter (where l.signal_led) as signal_led,
    count(*) filter (where exists (select 1 from touches t where t.lead_id = l.id and t.touch_no = 1)) as drafted,
    count(*) filter (where exists (select 1 from touches t where t.lead_id = l.id and t.touch_no = 1 and t.status = 'sent')) as sent,
    count(*) filter (where l.status = 'bounced') as bounced,
    count(*) filter (where l.status in ('replied', 'unsubscribed', 'booked')
      or exists (select 1 from touches t where t.lead_id = l.id and t.outcome in ('positive', 'negative', 'other', 'opt_out'))) as replied,
    count(*) filter (where l.status = 'booked'
      or exists (select 1 from touches t where t.lead_id = l.id and t.outcome = 'positive')) as positive,
    count(*) filter (where l.status = 'booked') as booked
  from leads l group by l.batch_id
)
select b.id as batch_id, b.name, b.city, b.state, b.created_at,
  coalesce(a.scraped, 0) as scraped, coalesce(a.cleaned, 0) as cleaned, coalesce(a.enriched, 0) as enriched,
  coalesce(a.signalled, 0) as signalled, coalesce(a.signal_led, 0) as signal_led, coalesce(a.drafted, 0) as drafted,
  coalesce(a.sent, 0) as sent, coalesce(a.bounced, 0) as bounced, coalesce(a.replied, 0) as replied,
  coalesce(a.positive, 0) as positive, coalesce(a.booked, 0) as booked,
  coalesce(c.apify_usd, 0) as apify_usd, coalesce(c.hunter_credits, 0) as hunter_credits,
  coalesce(c.serper_queries, 0) as serper_queries, coalesce(c.groq_tokens, 0) as groq_tokens,
  c.apify_usd / nullif(a.scraped, 0) as apify_usd_per_lead,
  c.apify_usd / nullif(a.enriched, 0) as apify_usd_per_verified_email,
  c.hunter_credits / nullif(a.enriched, 0) as hunter_credits_per_verified_email
from batches b left join agg a on a.batch_id = b.id left join cost c on c.batch_id = b.id;
