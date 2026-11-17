-- The send tick stamps today's computed allowance here; the Send page shows it (one source of truth: gtm/send.py).
alter table mailboxes add column if not exists allowance_today int;
alter table mailboxes add column if not exists allowance_date date;
