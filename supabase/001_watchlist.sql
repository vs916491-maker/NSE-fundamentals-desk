-- Fundamentals Desk: private watchlist (Stock page -> "Add to watchlist", Watchlist tab).
-- Each stock stays until you delete it or for 90 days after it was added
-- (removed automatically every night at 02:10 IST).
-- Run once in Supabase -> SQL Editor -> New query -> Run.

create table if not exists public.fd_watchlist (
  id bigserial primary key,
  symbol text not null,
  name text,
  added_at timestamptz not null default now(),
  price_added double precision,          -- last close when it was added
  price_date date,                       -- the day of that close
  note text,
  owner text default (auth.jwt() ->> 'email'),
  unique (symbol)
);

alter table public.fd_watchlist enable row level security;
drop policy if exists "owner manages fd watchlist" on public.fd_watchlist;
create policy "owner manages fd watchlist" on public.fd_watchlist for all to authenticated
  using ((auth.jwt() ->> 'email') = 'vs916491@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'vs916491@gmail.com');

-- nightly clean-up of entries older than 90 days (02:10 IST = 20:40 UTC)
do $$ begin
  if exists (select 1 from cron.job where jobname = 'fd-watchlist-cleanup') then
    perform cron.unschedule('fd-watchlist-cleanup');
  end if;
end $$;
select cron.schedule('fd-watchlist-cleanup', '40 20 * * *',
  $$delete from public.fd_watchlist where added_at < now() - interval '90 days'$$);
