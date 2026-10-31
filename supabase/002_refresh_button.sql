-- Fundamentals Desk, update 2: one-click "Refresh" button, like the F&O Desk's "Run scan".
-- The website adds a row to scan_requests (kind 'fundamentals'); the database then starts
-- the NSE-fundamentals-desk collection on GitHub with the token already stored in Vault.
-- Also moves the evening timers to the new refresh logic.
-- Run once in Supabase -> SQL Editor -> New query -> Run.

alter table public.scan_requests drop constraint if exists scan_requests_kind_check;
alter table public.scan_requests add constraint scan_requests_kind_check
  check (kind in ('screener', 'snapshot', 'sector', 'fundamentals'));

create or replace function public.on_scan_request()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  -- one run per kind every 3 minutes (10 for the Fundamentals Desk, whose run takes ~10 minutes),
  -- so repeated clicks don't stack up jobs
  if exists (select 1 from public.scan_requests
             where kind = new.kind and status = 'sent'
               and created_at > now() - case when new.kind = 'fundamentals' then interval '10 minutes'
                                             else interval '3 minutes' end) then
    new.status := 'skipped';
  elsif new.kind = 'fundamentals' then
    perform public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'collect.yml',
                                                 '{"args": "--auto --again"}'::jsonb);
    new.status := 'sent';
  else
    perform public.dispatch_workflow(
      case new.kind when 'snapshot' then 'index-snapshot.yml'
                    when 'sector' then 'sector-intraday.yml'
                    else 'stock-screener.yml' end, true);
    new.status := 'sent';
  end if;
  return new;
end;
$$;

-- evening timers, same times as before, now using the 2 PM / end-of-day refresh logic:
--   19:10 IST  end-of-day refresh + the daily email
--   23:30 IST  re-check for results filed late in the evening (no second email)
do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname like 'fundamentals-%' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
select cron.schedule('fundamentals-evening', '40 13 * * *',
  $$select public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'collect.yml', '{"args": "--auto"}'::jsonb)$$);
select cron.schedule('fundamentals-late', '0 18 * * *',
  $$select public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'collect.yml', '{"args": "--auto --again"}'::jsonb)$$);
