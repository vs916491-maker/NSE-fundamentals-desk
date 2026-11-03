-- Fundamentals Desk, update 3: Market News refresh every hour, 8 AM - 11 PM IST.
-- GitHub's own timer runs hours late, so Supabase starts the news job on time
-- (same stored GitHub token as the evening refresh).
-- Run once in Supabase -> SQL Editor -> New query -> Run.

do $$
declare j record;
begin
  for j in select jobname from cron.job where jobname = 'fundamentals-news' loop
    perform cron.unschedule(j.jobname);
  end loop;
end $$;
-- minute 35 of every hour from 02:35 to 17:35 UTC = 08:05 to 23:05 IST
select cron.schedule('fundamentals-news', '35 2-17 * * *',
  $$select public.dispatch_repo_workflow_inputs('NSE-fundamentals-desk', 'news.yml', '{"force": "false"}'::jsonb)$$);
